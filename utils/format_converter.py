import re


def markdown_to_plain_text(markdown_text):
    """
    将 Markdown 格式转换为纯文本
    """
    if not markdown_text:
        return ""

    # 移除 Markdown 格式标记
    text = str(markdown_text)

    # 移除粗体标记 **text** 或 __text__
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)

    # 移除斜体标记 *text* 或 _text_
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)

    # 移除代码块标记 ```code```
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)

    # 移除行内代码标记 `code`
    text = re.sub(r'`(.*?)`', r'\1', text)

    # 移除链接 [text](url)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    # 移除标题标记 # ## ###
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)

    # 移除列表标记 - * +
    text = re.sub(r'^[\s]*[-\*\+]\s*', '', text, flags=re.MULTILINE)

    # 移除数字列表标记 1. 2.
    text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)

    # 移除引用标记 >
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)

    # 清理多余的空行
    text = re.sub(r'\n\s*\n', '\n\n', text)

    return text.strip()


def prepare_report_data_for_word(analysis_content):
    """
    为 Word 报告准备数据，将 Markdown 转换为纯文本
    """
    return {
        'description': analysis_content.get('description', ''),
        'status_description': markdown_to_plain_text(analysis_content.get('status_description', '')),
        'analysis': markdown_to_plain_text(analysis_content.get('cause_analysis', '')),
        'suggestions': markdown_to_plain_text(analysis_content.get('supervision_suggestion', '')),
        'regulations': markdown_to_plain_text(analysis_content.get('regulations', ''))
    }


def prepare_report_data_for_frontend(analysis_content):
    """
    为前端准备数据，保持 Markdown 格式
    """
    return {
        'status_description': analysis_content.get('status_description', ''),
        'cause_analysis': analysis_content.get('cause_analysis', ''),
        'regulations': analysis_content.get('regulations', ''),
        'supervision_suggestion': analysis_content.get('supervision_suggestion', ''),
        'entities': analysis_content.get('entities', {})
    }