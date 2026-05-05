import { useMemo } from 'react'

interface SyncQRCodeProps {
  value: string
  size?: number
  className?: string
}

interface EcBlockGroup {
  blocks: number
  dataCodewords: number
}

interface VersionConfig {
  version: number
  ecCodewords: number
  groups: EcBlockGroup[]
}

interface QrMatrix {
  modules: boolean[][]
  size: number
}

const VERSION_CONFIGS: VersionConfig[] = [
  { version: 1, ecCodewords: 10, groups: [{ blocks: 1, dataCodewords: 16 }] },
  { version: 2, ecCodewords: 16, groups: [{ blocks: 1, dataCodewords: 28 }] },
  { version: 3, ecCodewords: 26, groups: [{ blocks: 1, dataCodewords: 44 }] },
  { version: 4, ecCodewords: 18, groups: [{ blocks: 2, dataCodewords: 32 }] },
  { version: 5, ecCodewords: 24, groups: [{ blocks: 2, dataCodewords: 43 }] },
  { version: 6, ecCodewords: 16, groups: [{ blocks: 4, dataCodewords: 27 }] },
  { version: 7, ecCodewords: 18, groups: [{ blocks: 4, dataCodewords: 31 }] },
  {
    version: 8,
    ecCodewords: 22,
    groups: [
      { blocks: 2, dataCodewords: 38 },
      { blocks: 2, dataCodewords: 39 },
    ],
  },
  {
    version: 9,
    ecCodewords: 22,
    groups: [
      { blocks: 3, dataCodewords: 36 },
      { blocks: 2, dataCodewords: 37 },
    ],
  },
  {
    version: 10,
    ecCodewords: 26,
    groups: [
      { blocks: 4, dataCodewords: 43 },
      { blocks: 1, dataCodewords: 44 },
    ],
  },
]

const ALIGNMENT_PATTERN_POSITIONS: Record<number, number[]> = {
  1: [],
  2: [6, 18],
  3: [6, 22],
  4: [6, 26],
  5: [6, 30],
  6: [6, 34],
  7: [6, 22, 38],
  8: [6, 24, 42],
  9: [6, 26, 46],
  10: [6, 28, 50],
}

const BYTE_MODE_INDICATOR = [0, 1, 0, 0]
const PAD_CODEWORDS = [0xec, 0x11]
const GF_EXP = new Array<number>(512)
const GF_LOG = new Array<number>(256)

let value = 1
for (let i = 0; i < 255; i += 1) {
  GF_EXP[i] = value
  GF_LOG[value] = i
  value <<= 1
  if (value & 0x100) value ^= 0x11d
}
for (let i = 255; i < 512; i += 1) {
  GF_EXP[i] = GF_EXP[i - 255]
}

function gfMultiply(left: number, right: number): number {
  if (left === 0 || right === 0) return 0
  return GF_EXP[GF_LOG[left] + GF_LOG[right]]
}

function getTotalDataCodewords(config: VersionConfig): number {
  return config.groups.reduce((total, group) => total + group.blocks * group.dataCodewords, 0)
}

function getCharacterCountBits(version: number): number {
  return version < 10 ? 8 : 16
}

function appendBits(target: number[], source: number, length: number): void {
  for (let i = length - 1; i >= 0; i -= 1) {
    target.push((source >>> i) & 1)
  }
}

function bitsToCodewords(bits: number[]): number[] {
  const result: number[] = []
  for (let i = 0; i < bits.length; i += 8) {
    let codeword = 0
    for (let offset = 0; offset < 8; offset += 1) {
      codeword = (codeword << 1) | bits[i + offset]
    }
    result.push(codeword)
  }
  return result
}

function encodeData(text: string, config: VersionConfig): number[] {
  const bytes = [...new TextEncoder().encode(text)]
  const capacityBits = getTotalDataCodewords(config) * 8
  const bits: number[] = []

  BYTE_MODE_INDICATOR.forEach((bit) => bits.push(bit))
  appendBits(bits, bytes.length, getCharacterCountBits(config.version))
  bytes.forEach((byte) => appendBits(bits, byte, 8))

  if (bits.length > capacityBits) {
    throw new Error('QR code payload exceeds the selected version capacity.')
  }

  const terminatorLength = Math.min(4, capacityBits - bits.length)
  for (let i = 0; i < terminatorLength; i += 1) {
    bits.push(0)
  }
  while (bits.length % 8 !== 0) {
    bits.push(0)
  }

  const codewords = bitsToCodewords(bits)
  let padIndex = 0
  while (codewords.length < getTotalDataCodewords(config)) {
    codewords.push(PAD_CODEWORDS[padIndex % PAD_CODEWORDS.length])
    padIndex += 1
  }
  return codewords
}

function createGeneratorPolynomial(degree: number): number[] {
  const result = new Array<number>(degree).fill(0)
  result[degree - 1] = 1

  let root = 1
  for (let i = 0; i < degree; i += 1) {
    for (let j = 0; j < degree; j += 1) {
      result[j] = gfMultiply(result[j], root)
      if (j + 1 < degree) {
        result[j] ^= result[j + 1]
      }
    }
    root = gfMultiply(root, 0x02)
  }

  return result
}

function createErrorCorrection(data: number[], degree: number): number[] {
  const generator = createGeneratorPolynomial(degree)
  const result = new Array<number>(degree).fill(0)

  data.forEach((codeword) => {
    const factor = codeword ^ result.shift()!
    result.push(0)
    generator.forEach((coefficient, index) => {
      result[index] ^= gfMultiply(coefficient, factor)
    })
  })

  return result
}

function interleaveCodewords(dataCodewords: number[], config: VersionConfig): number[] {
  const blocks: Array<{ data: number[]; ec: number[] }> = []
  let offset = 0

  config.groups.forEach((group) => {
    for (let i = 0; i < group.blocks; i += 1) {
      const data = dataCodewords.slice(offset, offset + group.dataCodewords)
      blocks.push({ data, ec: createErrorCorrection(data, config.ecCodewords) })
      offset += group.dataCodewords
    }
  })

  const result: number[] = []
  const maxDataLength = Math.max(...blocks.map((block) => block.data.length))
  for (let index = 0; index < maxDataLength; index += 1) {
    blocks.forEach((block) => {
      if (index < block.data.length) result.push(block.data[index])
    })
  }
  for (let index = 0; index < config.ecCodewords; index += 1) {
    blocks.forEach((block) => result.push(block.ec[index]))
  }

  return result
}

function cloneMatrix<T>(matrix: T[][]): T[][] {
  return matrix.map((row) => [...row])
}

function setModule(
  modules: boolean[][],
  reserved: boolean[][],
  x: number,
  y: number,
  isDark: boolean,
  isReserved = true
): void {
  if (y < 0 || y >= modules.length || x < 0 || x >= modules.length) return
  modules[y][x] = isDark
  if (isReserved) reserved[y][x] = true
}

function placeFinderPattern(modules: boolean[][], reserved: boolean[][], originX: number, originY: number): void {
  for (let dy = -1; dy <= 7; dy += 1) {
    for (let dx = -1; dx <= 7; dx += 1) {
      const x = originX + dx
      const y = originY + dy
      if (x < 0 || x >= modules.length || y < 0 || y >= modules.length) continue

      const isFinderArea = dx >= 0 && dx <= 6 && dy >= 0 && dy <= 6
      const isDark =
        isFinderArea &&
        (dx === 0 || dx === 6 || dy === 0 || dy === 6 || (dx >= 2 && dx <= 4 && dy >= 2 && dy <= 4))
      setModule(modules, reserved, x, y, isDark)
    }
  }
}

function placeAlignmentPattern(modules: boolean[][], reserved: boolean[][], centerX: number, centerY: number): void {
  for (let dy = -2; dy <= 2; dy += 1) {
    for (let dx = -2; dx <= 2; dx += 1) {
      const distance = Math.max(Math.abs(dx), Math.abs(dy))
      setModule(modules, reserved, centerX + dx, centerY + dy, distance !== 1)
    }
  }
}

function reserveFormatAreas(modules: boolean[][], reserved: boolean[][]): void {
  const size = modules.length
  for (let index = 0; index <= 8; index += 1) {
    if (index !== 6) {
      setModule(modules, reserved, 8, index, false)
      setModule(modules, reserved, index, 8, false)
    }
  }
  for (let index = 0; index < 8; index += 1) {
    setModule(modules, reserved, size - 1 - index, 8, false)
  }
  for (let index = 8; index < 15; index += 1) {
    setModule(modules, reserved, 8, size - 15 + index, false)
  }
}

function calculateBchCode(valueToEncode: number, polynomial: number): number {
  let result = valueToEncode
  const polynomialLength = Math.floor(Math.log2(polynomial)) + 1
  while (Math.floor(Math.log2(result)) + 1 >= polynomialLength) {
    const shift = Math.floor(Math.log2(result)) + 1 - polynomialLength
    result ^= polynomial << shift
  }
  return result
}

function writeFormatBits(modules: boolean[][], reserved: boolean[][], mask: number): void {
  const size = modules.length
  const errorCorrectionLevelM = 0
  const data = (errorCorrectionLevelM << 3) | mask
  const bits = ((data << 10) | calculateBchCode(data << 10, 0x537)) ^ 0x5412

  for (let index = 0; index <= 5; index += 1) {
    setModule(modules, reserved, 8, index, ((bits >>> index) & 1) === 1)
  }
  setModule(modules, reserved, 8, 7, ((bits >>> 6) & 1) === 1)
  setModule(modules, reserved, 8, 8, ((bits >>> 7) & 1) === 1)
  setModule(modules, reserved, 7, 8, ((bits >>> 8) & 1) === 1)
  for (let index = 9; index < 15; index += 1) {
    setModule(modules, reserved, 14 - index, 8, ((bits >>> index) & 1) === 1)
  }

  for (let index = 0; index < 8; index += 1) {
    setModule(modules, reserved, size - 1 - index, 8, ((bits >>> index) & 1) === 1)
  }
  for (let index = 8; index < 15; index += 1) {
    setModule(modules, reserved, 8, size - 15 + index, ((bits >>> index) & 1) === 1)
  }
}

function writeVersionBits(modules: boolean[][], reserved: boolean[][], version: number): void {
  if (version < 7) return

  const size = modules.length
  const bits = (version << 12) | calculateBchCode(version << 12, 0x1f25)
  for (let index = 0; index < 18; index += 1) {
    const bit = ((bits >>> index) & 1) === 1
    const x = size - 11 + (index % 3)
    const y = Math.floor(index / 3)
    setModule(modules, reserved, x, y, bit)
    setModule(modules, reserved, y, x, bit)
  }
}

function reserveVersionAreas(modules: boolean[][], reserved: boolean[][], version: number): void {
  if (version < 7) return

  const size = modules.length
  for (let y = 0; y < 6; y += 1) {
    for (let x = size - 11; x < size - 8; x += 1) {
      setModule(modules, reserved, x, y, false)
      setModule(modules, reserved, y, x, false)
    }
  }
}

function createFunctionPattern(version: number): { modules: boolean[][]; reserved: boolean[][] } {
  const size = 17 + version * 4
  const modules = Array.from({ length: size }, () => new Array<boolean>(size).fill(false))
  const reserved = Array.from({ length: size }, () => new Array<boolean>(size).fill(false))

  placeFinderPattern(modules, reserved, 0, 0)
  placeFinderPattern(modules, reserved, size - 7, 0)
  placeFinderPattern(modules, reserved, 0, size - 7)

  for (let index = 0; index < size; index += 1) {
    if (!reserved[6][index]) setModule(modules, reserved, index, 6, index % 2 === 0)
    if (!reserved[index][6]) setModule(modules, reserved, 6, index, index % 2 === 0)
  }

  const alignmentPositions = ALIGNMENT_PATTERN_POSITIONS[version]
  alignmentPositions.forEach((x) => {
    alignmentPositions.forEach((y) => {
      if (reserved[y][x]) return
      placeAlignmentPattern(modules, reserved, x, y)
    })
  })

  reserveFormatAreas(modules, reserved)
  reserveVersionAreas(modules, reserved, version)
  setModule(modules, reserved, 8, size - 8, true)

  return { modules, reserved }
}

function getMaskBit(mask: number, x: number, y: number): boolean {
  switch (mask) {
    case 0:
      return (x + y) % 2 === 0
    case 1:
      return y % 2 === 0
    case 2:
      return x % 3 === 0
    case 3:
      return (x + y) % 3 === 0
    case 4:
      return (Math.floor(y / 2) + Math.floor(x / 3)) % 2 === 0
    case 5:
      return ((x * y) % 2) + ((x * y) % 3) === 0
    case 6:
      return (((x * y) % 2) + ((x * y) % 3)) % 2 === 0
    case 7:
      return (((x + y) % 2) + ((x * y) % 3)) % 2 === 0
    default:
      return false
  }
}

function placeData(modules: boolean[][], reserved: boolean[][], codewords: number[], mask: number): void {
  const size = modules.length
  let bitIndex = 0

  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right -= 1
    for (let vertical = 0; vertical < size; vertical += 1) {
      const y = ((right + 1) & 2) === 0 ? size - 1 - vertical : vertical
      for (let columnOffset = 0; columnOffset < 2; columnOffset += 1) {
        const x = right - columnOffset
        if (reserved[y][x]) continue

        const codeword = codewords[Math.floor(bitIndex / 8)] ?? 0
        const bit = ((codeword >>> (7 - (bitIndex % 8))) & 1) === 1
        modules[y][x] = bit !== getMaskBit(mask, x, y)
        bitIndex += 1
      }
    }
  }
}

function getRunPenalty(line: boolean[]): number {
  let penalty = 0
  let runColor = line[0]
  let runLength = 1

  for (let index = 1; index < line.length; index += 1) {
    if (line[index] === runColor) {
      runLength += 1
    } else {
      if (runLength >= 5) penalty += 3 + runLength - 5
      runColor = line[index]
      runLength = 1
    }
  }
  if (runLength >= 5) penalty += 3 + runLength - 5

  return penalty
}

function hasFinderLikePattern(line: boolean[], start: number): boolean {
  const pattern = [true, false, true, true, true, false, true]
  for (let offset = 0; offset < pattern.length; offset += 1) {
    if (line[start + offset] !== pattern[offset]) return false
  }

  const beforeIsLight =
    start >= 4 &&
    !line[start - 1] &&
    !line[start - 2] &&
    !line[start - 3] &&
    !line[start - 4]
  const afterIsLight =
    start + 11 <= line.length &&
    !line[start + 7] &&
    !line[start + 8] &&
    !line[start + 9] &&
    !line[start + 10]

  return beforeIsLight || afterIsLight
}

function calculatePenalty(modules: boolean[][]): number {
  const size = modules.length
  let penalty = 0
  let darkCount = 0

  for (let y = 0; y < size; y += 1) {
    penalty += getRunPenalty(modules[y])
    modules[y].forEach((isDark) => {
      if (isDark) darkCount += 1
    })
    for (let x = 0; x <= size - 7; x += 1) {
      if (hasFinderLikePattern(modules[y], x)) penalty += 40
    }
  }

  for (let x = 0; x < size; x += 1) {
    const column = modules.map((row) => row[x])
    penalty += getRunPenalty(column)
    for (let y = 0; y <= size - 7; y += 1) {
      if (hasFinderLikePattern(column, y)) penalty += 40
    }
  }

  for (let y = 0; y < size - 1; y += 1) {
    for (let x = 0; x < size - 1; x += 1) {
      const color = modules[y][x]
      if (modules[y][x + 1] === color && modules[y + 1][x] === color && modules[y + 1][x + 1] === color) {
        penalty += 3
      }
    }
  }

  const totalModules = size * size
  const percent = (darkCount / totalModules) * 100
  penalty += Math.floor(Math.abs(percent - 50) / 5) * 10

  return penalty
}

function selectVersion(text: string): VersionConfig {
  const byteLength = new TextEncoder().encode(text).length
  const config = VERSION_CONFIGS.find((candidate) => {
    const dataBits = 4 + getCharacterCountBits(candidate.version) + byteLength * 8
    return dataBits <= getTotalDataCodewords(candidate) * 8
  })

  if (!config) {
    throw new Error('QR code payload is too long.')
  }
  return config
}

function createQrMatrix(text: string): QrMatrix {
  const config = selectVersion(text)
  const dataCodewords = encodeData(text, config)
  const codewords = interleaveCodewords(dataCodewords, config)
  const base = createFunctionPattern(config.version)

  let bestMatrix: boolean[][] | null = null
  let bestPenalty = Number.POSITIVE_INFINITY

  for (let mask = 0; mask < 8; mask += 1) {
    const modules = cloneMatrix(base.modules)
    const reserved = cloneMatrix(base.reserved)
    placeData(modules, reserved, codewords, mask)
    writeFormatBits(modules, reserved, mask)
    writeVersionBits(modules, reserved, config.version)

    const penalty = calculatePenalty(modules)
    if (penalty < bestPenalty) {
      bestPenalty = penalty
      bestMatrix = modules
    }
  }

  return { modules: bestMatrix!, size: base.modules.length }
}

export default function SyncQRCode({ value: qrValue, size = 184, className = '' }: SyncQRCodeProps) {
  const matrix = useMemo(() => {
    try {
      return qrValue ? createQrMatrix(qrValue) : null
    } catch {
      return null
    }
  }, [qrValue])

  if (!matrix) {
    return (
      <div
        className={`flex items-center justify-center rounded-md border border-dashed border-gray-300 bg-gray-50 text-center text-xs text-gray-500 ${className}`}
        style={{ height: size, width: size }}
      >
        暂无法生成二维码
      </div>
    )
  }

  const quietZone = 4
  const viewSize = matrix.size + quietZone * 2

  return (
    <svg
      aria-label="同步链接二维码"
      className={className}
      height={size}
      role="img"
      shapeRendering="crispEdges"
      viewBox={`0 0 ${viewSize} ${viewSize}`}
      width={size}
    >
      <rect fill="white" height={viewSize} width={viewSize} x="0" y="0" />
      {matrix.modules.map((row, y) =>
        row.map((isDark, x) =>
          isDark ? <rect fill="currentColor" height="1" key={`${x}-${y}`} width="1" x={x + quietZone} y={y + quietZone} /> : null
        )
      )}
    </svg>
  )
}
