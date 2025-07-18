import os
import json
import requests
import google.generativeai as genai
from feedgen.feed import FeedGenerator
from datetime import datetime, timezone

# --- 設定項目：ここをカスタマイズしてください ---

# Tavily APIで検索するキーワードのリスト
SEARCH_QUERIES = [
    "契約書 法改正 ニュース",
    "電子契約 最新動向",
    "下請法 ニュース 2024",
    "個人情報保護法 規約改定",
    "リーガルテック 契約業務"
]

# RSSフィードの基本情報
RSS_FEED_LINK = "https://github.com/momocatmeow-contract-news-rss/momocatmeow-contract-news-rss" 
RSS_FEED_TITLE = "AI厳選！契約書関連ニュース"
RSS_FEED_DESCRIPTION = "AIがWebから自動収集した契約関連の最新ニュースです。（本文表示）"
RSS_FILE_NAME = "feed.xml"

# --- Gemini APIへの指示（プロンプト） ---
GEMINI_PROMPT = """
あなたは、日本企業の法務担当者や弁護士向けに情報提供を行う、非常に優秀なAIアシスタントです。
以下のWeb記事の内容を分析し、契約実務、法改正、または関連するリーガルテックの動向について、専門家にとって価値のある重要な情報が含まれているか判断してください。

判断基準：
- 単なる製品紹介やイベント告知ではなく、実務に影響を与える具体的な情報（法改正、判例、新技術の法的論点など）を含んでいるか。
- 専門家が目を通すべき、示唆に富んだ内容か。

記事を分析した結果、重要だと判断した場合は、以下のJSON形式で結果を必ず出力してください。
{{
  "is_important": true,
  "title": "（記事のタイトルを簡潔に要約）",
  "category": "（「法改正」「電子契約」「判例」「M&A」「知財」など、最も適切なカテゴリを一つ）"
}}

重要ではない、または分析できないと判断した場合は、以下のJSON形式で出力してください。
{{
  "is_important": false
}}

--- 記事本文 ---
{article_text}
"""

# --- メインのプログラム（ここから下は通常変更不要です） ---

# APIキーを環境変数から読み込む
try:
    genai.configure(api_key=os.environ["GOOGLE_GEMINI_API_KEY"])
    tavily_api_key = os.environ["TAVILY_API_KEY"]
except KeyError:
    print("エラー: APIキーが環境変数に設定されていません。")
    print("GitHub ActionsのSecretsに GOOGLE_GEMINI_API_KEY と TAVILY_API_KEY を設定してください。")
    exit(1)


def search_with_tavily(query: str, max_results: int = 5) -> list:
    """Tavily APIを使ってWeb検索し、URLのリストを返す"""
    print(f"🔍 検索中: '{query}'")
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": tavily_api_key,
                "query": query,
                "search_depth": "basic",
                "include_images": False,
                "max_results": max_results
            }
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        urls = [res.get("url") for res in results if res.get("url")]
        print(f"✅ {len(urls)}件のURLが見つかりました。")
        return urls
    except requests.exceptions.RequestException as e:
        print(f"❌ Tavily APIでの検索エラー: {e}")
        return []

def get_article_content_from_jina(url: str) -> str | None:
    """Jina AI Readerを使ってURLから記事本文をMarkdown形式で抽出する"""
    print(f"📄 記事取得中: {url}")
    jina_reader_url = f"https://r.jina.ai/{url}"
    try:
        response = requests.get(jina_reader_url, timeout=60)
        response.raise_for_status()
        content = response.text
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if line.strip().startswith('#'):
                return '\n'.join(lines[i:])
        return content
    except requests.exceptions.RequestException as e:
        print(f"❌ Jina Readerでの記事取得エラー: {e}")
        return None

def analyze_with_gemini(article_text: str) -> dict | None: # 関数名を実態に合わせて変更
    """Gemini APIを使って記事を分析し、重要かどうかをJSON形式で返す"""
    print("🧠 Geminiによる分析中...")
    model = genai.GenerativeModel('gemini-1.5-flash')
    # プロンプトから "summary" の生成指示を削除
    prompt = GEMINI_PROMPT.format(article_text=article_text) 
    try:
        response = model.generate_content(prompt)
        cleaned_text = response.text.strip().replace("```json", "").replace("```", "").strip()
        result = json.loads(cleaned_text)
        print(f"✨ Geminiの分析完了: 重要か？ -> {result.get('is_important')}")
        return result
    except Exception as e:
        print(f"❌ Gemini APIでの分析エラー: {e}")
        try:
            print(f"応答テキスト: {response.text[:200]}") # デバッグ用に一部表示
        except NameError:
            pass
        return None


def main():
    """メイン処理を実行する"""
    print("🚀 プロジェクト開始")

    all_urls = set()
    for query in SEARCH_QUERIES:
        urls = search_with_tavily(query)
        for url in urls:
            all_urls.add(url)

    print(f"\n合計 {len(all_urls)}件のユニークなURLを処理します。")
    
    important_articles = []
    for url in all_urls:
        article_text = get_article_content_from_jina(url)
        if article_text:
            # ### 変更点 1: Geminiには分析だけをさせ、本文は別に保持する ###
            analysis_result = analyze_with_gemini(article_text)
            
            # Geminiが重要と判断した場合
            if analysis_result and analysis_result.get("is_important"):
                # 記事の情報を一つの辞書にまとめる
                article_data = {
                    'title': analysis_result.get("title", "No Title"),
                    'category': analysis_result.get("category", "N/A"),
                    'link': url,
                    'full_text': article_text # <- ここで記事本文を保持する
                }
                important_articles.append(article_data)

        print("-" * 20)

    if not important_articles:
        print("😭 AIが重要と判断した記事はありませんでした。")
        # 記事がない場合でも空のフィードを生成して上書きする
        fg = FeedGenerator()
        fg.title(RSS_FEED_TITLE)
        fg.link(href=RSS_FEED_LINK, rel='alternate')
        fg.description(RSS_FEED_DESCRIPTION)
        fg.rss_file(RSS_FILE_NAME, pretty=True)
        print("📝 空のRSSフィードを生成しました。")
        return

    print(f"\n🎉 {len(important_articles)}件の重要記事をRSSフィードとして生成します。")

    # RSSフィードの生成
    fg = FeedGenerator()
    fg.title(RSS_FEED_TITLE)
    fg.link(href=RSS_FEED_LINK, rel='alternate')
    fg.description(RSS_FEED_DESCRIPTION)

    # ### 変更点 2: descriptionに要約(summary)の代わりに記事本文(full_text)を入れる ###
    for article in important_articles:
        fe = fg.add_entry()
        fe.title(article.get("title"))
        fe.link(href=article.get("link"))
        
        category = article.get("category", "N/A")
        full_text_content = article.get("full_text", "記事本文が取得できませんでした。")
        
        # HTMLとしてdescriptionを構成する
        fe.description(f"<b>【カテゴリ】: {category}</b><br/><br/><hr/><br/>{full_text_content.replace('\n', '<br/>')}")

    # RSSファイルを保存
    fg.rss_file(RSS_FILE_NAME, pretty=True)
    print(f"✅ RSSファイル '{RSS_FILE_NAME}' を作成しました。")
    print("🏁 プロジェクト完了")


if __name__ == "__main__":
    main()
