export {}

declare global {
  interface Window {
    electronInfo?: {
      platform: string
      isElectron: true
    }
  }
}
