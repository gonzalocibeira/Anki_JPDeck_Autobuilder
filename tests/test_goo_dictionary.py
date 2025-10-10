import unittest

from goo_dictionary import extract_first_goo_definition


class GooDictionaryExtractionTests(unittest.TestCase):
    def test_extracts_description_from_json_ld_payload(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {
            "@context": "http://schema.org",
            "@type": "DefinedTerm",
            "name": "猫",
            "description": "ネコ科の哺乳類。イエネコの総称。"
        }
        </script>
        </head></html>
        """
        self.assertEqual(
            extract_first_goo_definition(html),
            "ネコ科の哺乳類。イエネコの総称。",
        )

    def test_extracts_from_nested_json_ld_list(self):
        html = """
        <script type="application/ld+json">
        [
            {
                "@type": "WebPage",
                "name": "dummy",
                "description": "not what we want"
            },
            {
                "@type": "DefinedTerm",
                "name": "走る",
                "description": "足を交互に動かして速く進む。"
            }
        ]
        </script>
        """
        self.assertEqual(
            extract_first_goo_definition(html),
            "足を交互に動かして速く進む。",
        )

    def test_falls_back_to_visible_meaning_block(self):
        html = """
        <div class="meaning">
            <p>鳥の総称。<br>空を飛ぶことができる脊椎動物。</p>
        </div>
        """
        self.assertEqual(
            extract_first_goo_definition(html),
            "鳥の総称。 空を飛ぶことができる脊椎動物。",
        )

    def test_returns_empty_string_when_nothing_found(self):
        html = "<html><body><p>no dictionary data</p></body></html>"
        self.assertEqual(extract_first_goo_definition(html), "")


if __name__ == "__main__":
    unittest.main()
