"""Agent の指示文と入力プロンプトに使う Jinja2 テンプレートを読み込む。"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

_jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), keep_trailing_newline=True)


def render_template(name: str, **context: object) -> str:
    """`templates/` ディレクトリのJinja2テンプレートをレンダリングする。

    [実装理由] Agentへの指示文や入力プロンプトをPythonコードから分離しつつ、調査担当と
    執筆担当が同じテンプレート探索規則を共有できるよう、読み込み処理をこのモジュールに
    集約している。

    Args:
        name: `templates/` ディレクトリ内のテンプレートファイル名。
        **context: テンプレートに渡す変数。

    Returns:
        レンダリング済みの文字列。
    """
    return _jinja_env.get_template(name).render(**context)
