import argparse
import json
from pathlib import Path

TEMPLATE_PATH = Path(__file__).with_name("template.html")


def build_html(payload) -> str:
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE_PATH.read_text(encoding="utf-8").replace("__DATA_JSON__", data_json)


def main() -> None:
    parser = argparse.ArgumentParser(description="ベンチマーク結果(JSON)をHTMLビューワに変換する")
    parser.add_argument("input", type=str)
    parser.add_argument("-o", "--output", type=str, default=None)
    args = parser.parse_args()
    input_path = Path(args.input)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    output_path = Path(args.output) if args.output else input_path.with_suffix(".html")
    output_path.write_text(build_html(payload), encoding="utf-8")
    print(f"{output_path} を生成しました")


if __name__ == "__main__":
    main()
