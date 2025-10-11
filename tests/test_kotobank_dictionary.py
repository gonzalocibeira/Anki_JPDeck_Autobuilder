from __future__ import annotations

import unittest

from kotobank_dictionary import extract_first_kotobank_definition


class KotobankDictionaryExtractionTests(unittest.TestCase):
    def test_extracts_definition_from_json_ld(self) -> None:
        html = """
        <html><head>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "description": "Kotobank（コトバンク）はオンライン辞書サービスです。"
        }
        </script>
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "DefinedTerm",
            "name": "テスト",
            "description": "最初に記載された説明文。"
        }
        </script>
        </head></html>
        """
        definition = extract_first_kotobank_definition(html)
        self.assertEqual(definition, "最初に記載された説明文。")

    def test_extracts_definition_from_primary_html_block(self) -> None:
        html = """
        <section class="kijiWrp">
            <div class="description">
                <p>説明文がここに記載されている。<br>改行も処理される。</p>
            </div>
        </section>
        """
        definition = extract_first_kotobank_definition(html)
        self.assertEqual(definition, "説明文がここに記載されている。 改行も処理される。")

    def test_ignores_noise_definitions(self) -> None:
        html = """
        <div class="description">
            <p>Kotobank（コトバンク）は朝日新聞社が提供する辞書サービスです。</p>
        </div>
        <dd class="description">
            本来の定義を返してほしい。
        </dd>
        """
        definition = extract_first_kotobank_definition(html)
        self.assertEqual(definition, "本来の定義を返してほしい。")


if __name__ == "__main__":
    unittest.main()
