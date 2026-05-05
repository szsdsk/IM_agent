import unittest

from backend.api.endpoints import (
    _looks_like_feedback,
    _looks_like_modification_request_command,
    _looks_like_new_generation,
)


class FeedbackDetectionTests(unittest.TestCase):
    def test_new_ppt_request_is_not_feedback(self):
        self.assertTrue(_looks_like_new_generation("生成一个新的原神 PPT"))
        self.assertFalse(_looks_like_feedback("生成一个新的原神 PPT"))

    def test_new_four_page_ppt_request_is_not_feedback(self):
        self.assertTrue(_looks_like_new_generation("生成一个 4 页的原神 PPT"))
        self.assertFalse(_looks_like_feedback("生成一个 4 页的原神 PPT"))

    def test_slide_page_revision_is_feedback(self):
        self.assertFalse(_looks_like_new_generation("第四页数据更详细一点"))
        self.assertTrue(_looks_like_feedback("第四页数据更详细一点"))

    def test_rehearsal_request_is_feedback(self):
        self.assertTrue(_looks_like_feedback("帮我生成排练讲稿和 Q&A"))

    def test_short_modification_command_opens_feedback_mode(self):
        self.assertTrue(_looks_like_modification_request_command("需要修改"))
        self.assertTrue(_looks_like_modification_request_command("修改一下"))

    def test_specific_revision_is_not_only_feedback_mode_command(self):
        self.assertFalse(_looks_like_modification_request_command("第 2 页加上英雄克制关系"))
        self.assertTrue(_looks_like_feedback("第 2 页加上英雄克制关系"))


if __name__ == "__main__":
    unittest.main()
