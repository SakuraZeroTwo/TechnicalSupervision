from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.shared import qn
import datetime
import os


def set_run_font(run, font_name='微软雅黑', font_size=12, bold=False):
    """
    设置 run 的字体，确保中文和英文都使用指定字体
    """
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.name = font_name

    # 确保中文字符也使用指定字体
    run._element.rPr.rFonts.set(qn('w:eastAsia'), font_name)
    run._element.rPr.rFonts.set(qn('w:ascii'), font_name)
    run._element.rPr.rFonts.set(qn('w:hAnsi'), font_name)
    run._element.rPr.rFonts.set(qn('w:cs'), font_name)


def add_formatted_paragraph(document, text, font_size=12, bold=False, alignment=None):
    """
    添加格式化段落，确保字体样式正确
    """
    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    set_run_font(run, '微软雅黑', font_size, bold)

    if alignment:
        paragraph.alignment = alignment

    return paragraph


def add_formatted_heading(document, text, level=1, font_size=14):
    """
    添加格式化标题
    """
    heading = document.add_heading(level=level)
    heading.clear()
    run = heading.add_run(text)
    set_run_font(run, '微软雅黑', font_size, True)

    return heading
def create_word_report(data: dict, image_path: str) -> str:
    """
    根据分析数据和图片生成 Word 报告.
    """
    document = Document()

    # --- 标题 ---
    title_para = document.add_paragraph()
    title_run = title_para.add_run('电力设备巡检报告')
    set_run_font(title_run, '微软雅黑', 18, True)
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # --- 元数据 ---
    add_formatted_paragraph(
        document,
        f"报告日期: {datetime.date.today().strftime('%Y-%m-%d')}",
        font_size=12,
        bold=False
    )

    add_formatted_paragraph(
        document,
        f"报告编号: EPIR-{datetime.date.today().strftime('%Y%m%d')}",
        font_size=12,
        bold=False
    )

    # 新增：添加阶段信息
    if 'stage' in data and data['stage']:
        add_formatted_paragraph(
            document,
            f"问题阶段: {data['stage']}",
            font_size=12,
            bold=False
        )

    add_formatted_paragraph(document, "-" * 20, font_size=12, bold=False)

    # --- 原始问题描述 ---
    add_formatted_heading(document, '1. 原始问题描述', level=1, font_size=14)
    add_formatted_paragraph(document, data.get('description', '无'), font_size=12, bold=False)

    # --- 新增：扩写后描述 ---
    if 'enhanced_description' in data and data['enhanced_description']:
        add_formatted_heading(document, '2. 扩写描述', level=1, font_size=14)
        add_formatted_paragraph(document, data.get('enhanced_description', '无'), font_size=12, bold=False)

    # --- 问题照片 ---
    add_formatted_heading(document, '3. 问题照片', level=1, font_size=14)
    try:
        document.add_picture(image_path, width=Inches(5.0))
    except FileNotFoundError:
        add_formatted_paragraph(document, "图片文件未找到。", font_size=12, bold=False)

    # --- 状态描述 ---
    add_formatted_heading(document, '4. 状态描述', level=1, font_size=14)
    add_formatted_paragraph(document, data.get('status_description', '无'), font_size=12, bold=False)

    # --- 原因分析 ---
    add_formatted_heading(document, '5. 原因分析', level=1, font_size=14)
    add_formatted_paragraph(document, data.get('analysis', '无'), font_size=12, bold=False)

    # --- 监督意见 ---
    add_formatted_heading(document, '6. 监督意见', level=1, font_size=14)
    add_formatted_paragraph(document, data.get('suggestions', '无'), font_size=12, bold=False)

    # --- 相关条例 ---
    add_formatted_heading(document, '7. 相关技术条例', level=1, font_size=14)
    if 'regulations' in data and data['regulations']:
        for idx, reg in enumerate(data['regulations'], 1):
            # 添加条例标题
            add_formatted_paragraph(document, f"{idx}. {reg['title']}", font_size=12, bold=True)

            # 添加监督依据
            if reg['basis']:
                add_formatted_paragraph(document, f"监督依据: {reg['basis']}", font_size=11)

            # 添加监督要点
            if reg['points']:
                add_formatted_paragraph(document, f"监督要点: {reg['points']}", font_size=11)

            # 添加监督要求
            if reg['requirements']:
                add_formatted_paragraph(document, f"监督要求: {reg['requirements']}", font_size=11)

            # 添加分隔符
            if idx < len(data['regulations']):
                add_formatted_paragraph(document, "-" * 40, font_size=10)
    else:
        add_formatted_paragraph(document, "未找到相关技术监督条例", font_size=12)

    # --- 保存文件 ---
    output_filename = f"report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    output_path = os.path.join('static', 'reports', output_filename)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    document.save(output_path)
    return output_path