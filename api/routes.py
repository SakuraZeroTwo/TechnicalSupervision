import jieba
from flask import Blueprint, request, jsonify, current_app, send_from_directory
from werkzeug.utils import secure_filename
import os
import json
import warnings

# 忽略openpyxl的样式警告
warnings.filterwarnings("ignore", category=UserWarning,
                        message="Workbook contains no default style, apply openpyxl's default")

# 导入服务
from services.vlm_service import get_vlm_analysis
from services.neo4j_service import neo4j_service
from services.word_service import create_word_report
from services.file_service import file_service


# 创建一个蓝图
api_bp = Blueprint('api', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@api_bp.route('/analyze', methods=['POST'])
def analyze_issue():
    """
    核心功能端点：接收图片、描述和阶段，返回完整分析和报告链接
    """
    # 1. 检查表单数据

    description = request.form.get('description', '')
    if not description:
        return jsonify({"error": "请求中未找到问题描述"}), 400

    # 获取阶段参数
    stage = request.form.get('stage', None)

    # 是否生成报告
    generate_word = request.form.get('generate_word', 'true').lower() == 'true'

    # 2.处理可选的图片
    image_path = None
    if 'image' in request.files and request.files['image'].filename:
        file = request.files['image']
        if file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            file.save(image_path)
        elif file.filename != '':
            return jsonify({"error": "无效的图片文件"}), 400

    # 3. 调用 VLM 服务进行分析,传入阶段参数
    vlm_result = get_vlm_analysis(description, image_path, stage)

    if "error" in vlm_result:
        return jsonify({"error": "调用VLM模型失败", "details": vlm_result.get('error')}), 500

    # 4. 解析 VLM 返回的 JSON 结果
    try:
        raw_content = vlm_result['content']
        # 清理模型返回的字符串 ---
        # 模型可能返回被 Markdown 包裹的 JSON，例如 ```json\n{...}\n```，需要提取出纯净的 JSON 字符串
        if '```' in raw_content:
            # 找到第一个 '{' 和最后一个 '}' 来提取 JSON 对象
            start_index = raw_content.find('{')
            end_index = raw_content.rfind('}')
            if start_index != -1 and end_index != -1:
                json_string = raw_content[start_index:end_index + 1]
            else:
                json_string = raw_content  # 如果找不到，则按原样尝试
        else:
            json_string = raw_content

        analysis_content = json.loads(json_string)
    except (json.JSONDecodeError, KeyError) as e:
        return jsonify(
            {"error": "解析VLM返回结果失败", "details": str(e), "raw_vlm_output": vlm_result.get('content')}), 500

    # 5. 从分析中提取关键信息
    entities_list = []
    entities_data = analysis_content.get('entities', [])
    if isinstance(entities_data, list):
        entities_list = entities_data
    elif isinstance(entities_data, str):
        entities_list = [e.strip() for e in entities_data.split(',')]

    # 添加原始描述中的关键词作为实体
    if description:
        description_keywords = [w for w in jieba.lcut(description) if len(w) >= 2]
        for kw in description_keywords:
            if kw not in entities_list:
                entities_list.append(kw)

    recognized_stage = analysis_content.get('stage', stage if stage else '运维检修阶段')
    enhanced_description = analysis_content.get('enhanced_description', description)  # 获取扩写后的描述

    # 6. 使用文件服务检索规范条例
    retrieved_regulations = []
    if entities_list:
        try:
            clean_stage = recognized_stage.replace("阶段", "") if recognized_stage else "运维检修"
            retrieved_regulations = file_service.find_regulations_by_stage_and_keywords(clean_stage, entities_list)
        except Exception as e:
            current_app.logger.error(f"文件检索错误: {str(e)}")

    # 7. 【最终简化逻辑】直接选用第一条检索到的条例
    best_regulation = {}
    if retrieved_regulations:
        # file_service 返回的结果已经按相关性排序，直接取第一个即可
        best_regulation = retrieved_regulations[0]

    # 8. 准备最终响应
    final_response = {
        "vlm_analysis": analysis_content,
        "historical_cases": file_service.find_historical_cases_by_entities(entities_list, recognized_stage),
        "regulations": [best_regulation] if best_regulation else [],
    }

    # 9. 生成Markdown格式内容
    final_response["markdown"] = generate_custom_markdown(
        analysis_content,
        [best_regulation] if best_regulation else [],
        final_response["historical_cases"],
        final_response.get("report_url")
    )

    # 10. 如果需要生成Word报告
    if generate_word:
        word_report_data = {
            'stage': recognized_stage,
            'regulation': best_regulation,
            'description': enhanced_description,
            'analysis': analysis_content.get('cause_analysis', ''),
            'suggestions': analysis_content.get('supervision_suggestion', ''),
        }
        report_path = create_word_report(word_report_data, image_path)
        report_url = request.host_url + 'api/static/reports/' + os.path.basename(report_path)
        final_response["report_url"] = report_url

        # 更新Markdown内容以包含报告链接
        final_response["markdown"] = generate_custom_markdown(
            analysis_content,
            [best_regulation] if best_regulation else [],
            final_response["historical_cases"],
            report_url
        )

    return jsonify(final_response)


@api_bp.route('/graph', methods=['POST'])
def graph_analysis_from_text():
    # 1. 从表单中获取描述
    #  --- START: 这是新的实现方式 ---
    description = request.form.get('description')
    if not description:
        return jsonify({"error": "表单中未找到 'description' 字段或该字段为空"}), 400
    # --- END: 这是新的实现方式 ---

    # 2. 调用 VLM 服务进行分析和实体提取
    vlm_result = get_vlm_analysis(description, image_path=None)
    if "error" in vlm_result:
        return jsonify({"error": "调用VLM模型进行实体识别失败", "details": vlm_result.get('error')}), 500

    # 3. 解析 VLM 结果
    try:
        raw_content = vlm_result['content']
        if '```' in raw_content:
            start_index = raw_content.find('{')
            end_index = raw_content.rfind('}')
            json_string = raw_content[
                          start_index:end_index + 1] if start_index != -1 and end_index != -1 else raw_content
        else:
            json_string = raw_content
        analysis_content = json.loads(json_string)
    except (json.JSONDecodeError, KeyError) as e:
        return jsonify(
            {"error": "解析VLM实体识别结果失败", "details": str(e), "raw_vlm_output": vlm_result.get('content')}), 500

    entities_list = []
    entities_data = analysis_content.get('entities', [])
    if isinstance(entities_data, list):
        entities_list = entities_data
    elif isinstance(entities_data, str):
        # 处理模型可能返回逗号分隔的字符串的情况
        entities_list = [e.strip() for e in entities_data.split(',') if e.strip()]

    if not entities_list:
        return jsonify({"message": "未能从描述中识别出有效实体", "subgraph": {"nodes": [], "links": []}}), 200

    # 5. 调用 Neo4j 服务进行图数据库检索
    try:
        subgraph_data = neo4j_service.get_subgraph_for_entities(entities_list)
        return jsonify({
            "entities_found": entities_list,
            "subgraph": subgraph_data
        })
    except Exception as e:
        current_app.logger.error(f"图数据库检索失败: {str(e)}")
        return jsonify({"error": "图数据库检索时发生内部错误", "details": str(e)}), 500


# 生成自定义markdown内容
def generate_custom_markdown(vlm_analysis, regulations=None, historical_cases=None, report_url=None):
    """生成专注于大模型分析结果的Markdown"""
    markdown = []

    # 添加标题
    markdown.append("# 电力设备技术监督分析报告\n")

    # 添加问题描述
    if "enhanced_description" in vlm_analysis:
        markdown.append("## 问题描述\n")
        markdown.append(vlm_analysis["enhanced_description"])
        markdown.append("\n")

    # 添加设备状态评估（强调严重性）
    if "status_description" in vlm_analysis:
        markdown.append("## 设备状态评估\n")
        status_text = vlm_analysis["status_description"]
        # 尝试提取或标记严重程度
        if "严重" in status_text:
            markdown.append("**严重程度: 严重** ⚠️\n")
        elif "一般" in status_text:
            markdown.append("**严重程度: 一般** ℹ️\n")
        else:
            markdown.append("**严重程度: 需进一步评估** ⚠️\n")
        markdown.append(status_text)
        markdown.append("\n")

    # 添加漏油可能性评估（如果有相关内容）
    cause_analysis = vlm_analysis.get("cause_analysis", "")
    if "漏油" in cause_analysis or "渗油" in cause_analysis:
        markdown.append("## 漏油可能性分析\n")
        # 尝试从原因分析中提取与漏油相关的内容
        if "高" in cause_analysis and ("可能" in cause_analysis or "风险" in cause_analysis):
            markdown.append("**漏油风险评估: 高风险** ⚠️\n")
        elif "低" in cause_analysis and ("可能" in cause_analysis or "风险" in cause_analysis):
            markdown.append("**漏油风险评估: 低风险** ℹ️\n")
        else:
            markdown.append("**漏油风险评估: 需监测** ⚠️\n")
        markdown.append(cause_analysis)
        markdown.append("\n")
    else:
        # 如果没有明确提到漏油，仍然保留原因分析部分
        markdown.append("## 原因分析\n")
        markdown.append(cause_analysis)
        markdown.append("\n")

    # 添加监督建议
    if "supervision_suggestion" in vlm_analysis:
        markdown.append("## 监督建议\n")
        markdown.append(vlm_analysis["supervision_suggestion"])
        markdown.append("\n")

    # 添加阶段信息
    if "stage" in vlm_analysis:
        markdown.append(f"**适用阶段**: {vlm_analysis['stage']}")
        markdown.append("\n")

    # 添加规范参考（简化显示）
    if regulations and len(regulations) > 0:
        markdown.append("## 相关技术规范\n")
        reg = regulations[0]
        markdown.append(f"### {reg.get('title', '技术规范')}\n")
        if reg.get("basis"):
            markdown.append(f"**监督依据**: {reg['basis']}\n")
        if reg.get("requirements"):
            markdown.append(f"**监督要求**: {reg['requirements']}\n")
        markdown.append("\n")

    # 添加历史案例（简化显示，只展示最相关的2-3个）
    if historical_cases and len(historical_cases) > 0:
        markdown.append("## 相似历史案例\n")
        for i, case in enumerate(historical_cases[:3], 1):
            markdown.append(f"### 案例 {i}: {case.get('title', '未命名案例')}\n")
            if case.get("description"):
                # 截取简短描述
                desc = case['description']
                short_desc = desc[:100] + "..." if len(desc) > 100 else desc
                markdown.append(f"**问题概述**: {short_desc}\n")
            if case.get("solution") and case["solution"] != "未提供解决方案":
                markdown.append(f"**解决方案**: {case['solution'][:150]}...\n")
            markdown.append("\n")

    # 添加报告下载链接
    if report_url:
        markdown.append(f"## 完整报告\n[点击下载详细Word报告]({report_url})\n")

    return "\n".join(markdown)
# 添加阶段获取端点
@api_bp.route('/stages', methods=['GET'])
def get_available_stages():
    """获取系统中所有可用的阶段列表"""
    stages = [
        "规划可研阶段",
        "工程设计阶段",
        "设备采购阶段",
        "设备制造阶段",
        "设备验收阶段",
        "设备安装阶段",
        "设备调试阶段",
        "竣工验收阶段",
        "运维检修阶段",
        "退役报废阶段"
    ]
    return jsonify({"stages": stages})


# 添加单独的案例检索端点
@api_bp.route('/search/cases', methods=['POST'])
def search_historical_cases():
    """根据关键词和可选阶段搜索历史案例"""
    data = request.json

    if not data or 'keywords' not in data:
        return jsonify({"error": "请提供搜索关键词"}), 400

    keywords = data.get('keywords', [])
    stage = data.get('stage', None)

    try:
        results = file_service.find_historical_cases_by_entities(keywords, stage)
        return jsonify({"cases": results})
    except Exception as e:
        return jsonify({"error": f"搜索失败: {str(e)}"}), 500


