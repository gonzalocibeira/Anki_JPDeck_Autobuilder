import unittest

from wiktionary_parser import extract_first_japanese_definition


class ExtractFirstJapaneseDefinitionTests(unittest.TestCase):
    def test_handles_numbered_definition(self) -> None:
        extract = """
日本語

名詞
1. 猫。かわいい動物。
語源
"""
        self.assertEqual(
            extract_first_japanese_definition(extract),
            "猫。かわいい動物。",
        )

    def test_handles_section_heading_with_equals(self) -> None:
        extract = """
==日本語==
===名詞===
・犬。忠実な哺乳類。
===熟語===
"""
        self.assertEqual(
            extract_first_japanese_definition(extract),
            "犬。忠実な哺乳類。",
        )

    def test_handles_heading_with_spaces(self) -> None:
        extract = """
== 日本語 ==
=== 名詞 ===
# 狐。ずる賢い動物。
"""
        self.assertEqual(
            extract_first_japanese_definition(extract),
            "狐。ずる賢い動物。",
        )

    def test_fallback_to_first_sentence_when_no_japanese_section(self) -> None:
        extract = """
これは日本語の説明が得られなかった場合の文章。二文目。
"""
        self.assertEqual(
            extract_first_japanese_definition(extract),
            "これは日本語の説明が得られなかった場合の文章。",
        )

    def test_ignores_part_of_speech_marker_with_colon(self) -> None:
        extract = """
日本語

名詞：
① 鳥。空を飛ぶ生き物。
"""
        self.assertEqual(
            extract_first_japanese_definition(extract),
            "鳥。空を飛ぶ生き物。",
        )


if __name__ == "__main__":
    unittest.main()
