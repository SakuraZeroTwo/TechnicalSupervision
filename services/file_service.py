# services/file_service.py
import os
import pandas as pd
import jieba
import re
from docx import Document
from pathlib import Path
import json


class FileService:
    def __init__(self):
        # 基础路径配置
        self.base_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'files')
        self.regulations_path = os.path.join(self.base_path, '技术监督条例导出')
        self.cases_path = os.path.join(self.base_path, '技术监督典型案例-电科院')
        self.excel_path = os.path.join(self.base_path, '标准excel')
        self.problem_path = os.path.join(self.base_path, '技术监督问题与条例')
        self.transformer_cases_path = os.path.join(self.base_path, '甘肃电力变压器故障案例')

        # 阶段映射字典
        self._stage_dict = {
            "规划可研": ["规划可研阶段", "规划", "可研", "前期"],
            "工程设计": ["设计阶段", "工程设计", "设计"],
            "设备采购": ["采购阶段", "设备采购", "物资采购", "采购"],
            "设备制造": ["制造阶段", "设备制造", "制造"],
            "设备验收": ["验收阶段", "设备验收", "出厂验收"],
            "设备安装": ["安装阶段", "设备安装", "安装"],
            "设备调试": ["调试阶段", "设备调试", "调试"],
            "竣工验收": ["竣工验收阶段", "竣工验收", "竣工"],
            "运维检修": ["运行维护阶段", "运维检修", "运行", "维护", "检修"],
            "退役报废": ["退役报废阶段", "退役", "报废"]
        }

        # 初始化索引
        self._build_indices()

    def _find_columns_in_excel(self, file_path, sheet_name):
        """识别Excel中的关键列，处理表头在第3行的情况"""
        # 读取原始数据，不指定表头
        df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

        # 定义可能的列名及其别名
        column_mappings = {
            '监督依据': ['监督依据', '依据', '技术依据', '标准依据', '规范依据'],
            '监督要点': ['监督要点', '要点', '监督重点', '检查要点', '关键点'],
            '监督要求': ['监督要求', '要求', '技术要求', '规范要求', '检查要求']
        }

        # 表头通常在第3行（索引为2）
        header_row_idx = 2
        col_indices = {}

        # 遍历第3行查找列名
        if len(df_raw) > header_row_idx:
            for col_idx, cell_value in enumerate(df_raw.iloc[header_row_idx]):
                if pd.notna(cell_value):
                    cell_str = str(cell_value).strip()
                    for target_col, aliases in column_mappings.items():
                        if cell_str in aliases or any(alias in cell_str for alias in aliases):
                            col_indices[target_col] = col_idx
                            print(f"    在第{header_row_idx + 1}行找到列名'{target_col}'，位置: 第{col_idx + 1}列")

        # 如果没找到，尝试其他行（第1-5行）
        if not col_indices:
            for row_idx in range(min(5, len(df_raw))):
                if row_idx == header_row_idx:
                    continue  # 已经检查过的行跳过
                for col_idx, cell_value in enumerate(df_raw.iloc[row_idx]):
                    if pd.notna(cell_value):
                        cell_str = str(cell_value).strip()
                        for target_col, aliases in column_mappings.items():
                            if cell_str in aliases or any(alias in cell_str for alias in aliases):
                                col_indices[target_col] = col_idx
                                print(f"    在第{row_idx + 1}行找到列名'{target_col}'，位置: 第{col_idx + 1}列")

        # 数据从列名行的下一行开始
        data_start_row = header_row_idx + 1

        # 创建结果字典
        column_data = {}
        for target_col, col_idx in col_indices.items():
            if data_start_row < len(df_raw):
                column_data[target_col] = df_raw.iloc[data_start_row:, col_idx]

        return column_data, col_indices
    def _build_indices(self):
        """构建文件索引，提高检索效率"""
        print("正在构建文件索引...")
        self.regulation_files = self._scan_files(self.regulations_path, ['.xls', '.xlsx'])
        self.case_files = self._scan_files(self.cases_path, ['.docx', '.doc'])
        self.excel_files = self._scan_files(self.excel_path, ['.xls', '.xlsx'])
        self.problem_files = self._scan_files(self.problem_path, ['.xls', '.xlsx'])
        self.transformer_files = self._scan_files(self.transformer_cases_path, ['.docx', '.doc', '.pdf'])
        print(f"索引构建完成，共找到 {len(self.regulation_files)} 条技术条例文件，{len(self.case_files)} 条案例文件")

    def _scan_files(self, directory, extensions):
        """扫描指定目录下的所有符合扩展名的文件"""
        files = []
        if os.path.exists(directory):
            for root, _, filenames in os.walk(directory):
                for filename in filenames:
                    if any(filename.lower().endswith(ext) for ext in extensions) and not filename.startswith('~$'):
                        files.append(os.path.join(root, filename))
        return files

    def _text_similarity(self, text1, text2):
        """计算两段文本的相似度，使用简单的词集合相似度"""
        if not text1 or not text2:
            return 0
        words1 = set(jieba.cut(str(text1)))
        words2 = set(jieba.cut(str(text2)))
        common_words = words1.intersection(words2)
        return len(common_words) / max(len(words1), len(words2), 1)

    def find_regulations_by_stage_and_keywords(self, stage, keywords, max_results=5):
        """根据阶段和关键词从技术监督条例中查找相关内容"""
        results = []
        processed_files = 0
        matched_files = 0

        # 记录查询信息
        print(f"开始查询 - 阶段: {stage}, 关键词: {keywords}")

        # 处理关键词格式
        if isinstance(keywords, str):
            keywords = [keywords]

        # 拆分复合关键词,如"变压器跳闸"同时匹配"变压器"和"跳闸"
        expanded_keywords = []
        for keyword in keywords:
            expanded_keywords.append(keyword)
            # 使用jieba分词处理复合关键词
            if len(keyword) > 2:
                parts = jieba.lcut(keyword)
                for part in parts:
                    if len(part) >= 2 and part not in expanded_keywords:
                        expanded_keywords.append(part)

        print(f"扩展后的关键词: {expanded_keywords}")

        # 标准化阶段名称
        normalized_stage = self._normalize_stage(stage)
        print(f"标准化后的阶段: {normalized_stage}")

        # --------- 新增: 首先根据文件名筛选相关条例文件 ---------
        filtered_files = []
        for file_path in self.regulation_files:
            file_name = os.path.basename(file_path)
            # 检查文件名是否包含任何关键词
            if any(kw in file_name for kw in expanded_keywords):
                filtered_files.append((file_path, 2))  # 文件名匹配的权重更高
            elif any(kw in file_name.lower() for kw in expanded_keywords):
                filtered_files.append((file_path, 1))  # 不区分大小写的匹配权重稍低

        # 如果没有找到文件名匹配的条例，使用所有条例文件
        if not filtered_files:
            print("文件名中未找到匹配关键词的条例，将搜索所有条例文件")
            filtered_files = [(file_path, 0) for file_path in self.regulation_files]
        else:
            print(f"找到 {len(filtered_files)} 个文件名包含关键词的条例文件")

        # 按匹配权重排序，优先处理文件名匹配的条例
        filtered_files.sort(key=lambda x: x[1], reverse=True)

        # 遍历筛选后的条例文件
        for file_path, name_match_score in filtered_files:
            try:
                file_name = os.path.basename(file_path)
                print(f"处理文件: {file_name}" + (" (文件名匹配)" if name_match_score > 0 else ""))
                processed_files += 1
                xls = pd.ExcelFile(file_path)

                # 更灵活的工作表匹配策略
                target_sheets = []

                # 1. 精确匹配阶段名
                for sheet_name in xls.sheet_names:
                    if normalized_stage.lower() in sheet_name.lower():
                        target_sheets.append(sheet_name)

                # 2. 部分匹配
                if not target_sheets:
                    stage_keywords = self._stage_dict.get(normalized_stage, [normalized_stage])
                    for sheet_name in xls.sheet_names:
                        if any(kw.lower() in sheet_name.lower() for kw in stage_keywords):
                            target_sheets.append(sheet_name)

                # 3. 通用工作表匹配
                if not target_sheets and normalized_stage == "运维检修":
                    for sheet_name in xls.sheet_names:
                        if any(kw in sheet_name.lower() for kw in ["运行", "运维", "检修", "维护"]):
                            target_sheets.append(sheet_name)

                # 4. 文件名关键词匹配
                if not target_sheets:
                    if any(kw.lower() in file_name.lower() for kw in expanded_keywords):
                        target_sheets = xls.sheet_names[:1]  # 使用第一个工作表
                        print(f"根据文件名匹配关键词，使用第一个工作表: {target_sheets}")

                # 5. 最后手段: 处理所有工作表
                if not target_sheets:
                    target_sheets = [xls.sheet_names[0]]
                    print(f"未找到匹配的工作表，将处理第一个工作表: {target_sheets[0]}")

                # 处理选定的工作表
                for sheet_name in target_sheets:
                    try:
                        print(f"  处理工作表: {sheet_name}")

                        # 使用新函数查找列
                        column_data, col_indices = self._find_columns_in_excel(file_path, sheet_name)

                        if not column_data:
                            print(f"  工作表 {sheet_name} 未找到相关列，尝试固定行位置方案")
                            # 尝试固定位置方案
                            df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
                            if len(df.columns) >= 6:  # 确保有足够的列
                                # 根据常见Excel格式，尝试使用固定位置
                                # 通常第3行包含列名，第4行开始是数据
                                header_row = 2  # 索引从0开始，所以第3行是索引2
                                data_start_row = header_row + 1

                                # 尝试推断列的位置
                                potential_columns = {
                                    '监督依据': None,
                                    '监督要点': None,
                                    '监督要求': None
                                }

                                # 在第3行查找列名
                                if len(df) > header_row:
                                    for col_idx in range(len(df.columns)):
                                        cell_value = df.iloc[header_row, col_idx]
                                        if pd.notna(cell_value):
                                            cell_str = str(cell_value).strip()
                                            if '依据' in cell_str or '规范' in cell_str or '标准' in cell_str:
                                                potential_columns['监督依据'] = col_idx
                                            elif '要点' in cell_str or '重点' in cell_str or '点' in cell_str:
                                                potential_columns['监督要点'] = col_idx
                                            elif '要求' in cell_str or '措施' in cell_str:
                                                potential_columns['监督要求'] = col_idx

                                # 为找到的列创建数据
                                column_data = {}
                                for col_name, col_idx in potential_columns.items():
                                    if col_idx is not None and data_start_row < len(df):
                                        column_data[col_name] = df.iloc[data_start_row:, col_idx]
                                        print(f"    根据位置找到列 '{col_name}'，位置: 第{col_idx + 1}列")

                                # 如果仍然找不到所需列，尝试常用列位置
                                if not column_data and len(df.columns) >= 6:
                                    print(f"    使用固定列位置索引")
                                    column_data = {
                                        '监督依据': df.iloc[data_start_row:, 4] if 4 < len(df.columns) else None,
                                        '监督要点': df.iloc[data_start_row:, 5] if 5 < len(df.columns) else None,
                                        '监督要求': df.iloc[data_start_row:, 6] if 6 < len(df.columns) else None
                                    }
                                    column_data = {k: v for k, v in column_data.items() if v is not None}

                        # 如果仍然没有找到列
                        if not column_data:
                            print(f"  工作表 {sheet_name} 未找到相关列")
                            continue

                        print(f"  在工作表 {sheet_name} 找到列: {list(column_data.keys())}")

                        # 处理每一行数据
                        for idx in range(len(next(iter(column_data.values())))):
                            row_data = {}
                            match_score = 0

                            # 提取当前行的每列数据
                            for col_name, col_data in column_data.items():
                                if idx < len(col_data) and pd.notna(col_data.iloc[idx]):
                                    value = str(col_data.iloc[idx]).strip()
                                    row_data[col_name] = value

                                    # 计算与关键词的匹配程度
                                    for keyword in expanded_keywords:
                                        if keyword.lower() in value.lower():
                                            match_score += 1
                                            print(f"    在{col_name}列发现关键词'{keyword}'")
                                        # 针对复杂关键词，分词后单独匹配
                                        elif len(keyword) > 2:
                                            for part in jieba.lcut(keyword):
                                                if len(part) >= 2 and part.lower() in value.lower():
                                                    match_score += 0.5
                                                    print(f"    在{col_name}列发现关键词部分'{part}'")

                            # 添加文件名匹配的额外分数
                            match_score += name_match_score * 0.5

                            # 如果有足够的匹配分数，添加到结果中
                            if match_score > 0:
                                # 获取标题
                                title = f"{os.path.basename(file_path)} - {sheet_name}"
                                # 如果有标题列，尝试获取
                                if idx > 0:
                                    try:
                                        df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

                                        # 检查是否有可能的标题列
                                        for col_idx in [0, 1]:  # 通常第一列或第二列包含标题
                                            if col_idx < len(df.columns):
                                                title_value = df.iloc[idx + data_start_row, col_idx]
                                                if pd.notna(title_value) and len(str(title_value).strip()) > 0:
                                                    title = str(title_value).strip()
                                                    break
                                    except Exception as title_err:
                                        print(f"    获取标题时出错: {str(title_err)}")

                                result = {
                                    'title': title,
                                    'basis': row_data.get('监督依据', ''),
                                    'points': row_data.get('监督要点', ''),
                                    'requirements': row_data.get('监督要求', ''),
                                    'match_score': match_score,
                                    'source': {
                                        'file': os.path.basename(file_path),
                                        'sheet': sheet_name
                                    }
                                }
                                results.append(result)
                                matched_files += 1
                                print(f"    找到匹配项，分数: {match_score}")

                    except Exception as e:
                        print(f"处理工作表 {sheet_name} 时出错: {str(e)}")
                        import traceback
                        print(traceback.format_exc())
                        continue

            except Exception as e:
                print(f"处理文件 {file_path} 时出错: {str(e)}")
                continue

        print(f"检索统计: 处理了{processed_files}个文件, 匹配到{matched_files}个结果")

        # 根据匹配分数排序并去重
        unique_results = {}
        for result in results:
            key = f"{result['basis']}_{result['points']}_{result['requirements']}"
            if key not in unique_results or result['match_score'] > unique_results[key]['match_score']:
                unique_results[key] = result

        final_results = list(unique_results.values())
        final_results.sort(key=lambda x: x['match_score'], reverse=True)

        return final_results[:max_results]

    def _find_column_by_keywords(self, df, keywords):
        """查找包含指定关键词的列"""
        for col in df.columns:
            col_str = str(col).lower()
            for keyword in keywords:
                if keyword.lower() in col_str:
                    return col
        return None

    def _normalize_stage(self, stage):
        """将阶段名称标准化为系统内部使用的格式"""
        if not stage:
            return "运维检修"

        # 移除"阶段"字样以提高匹配率
        clean_stage = stage.replace("阶段", "")

        for key, aliases in self._stage_dict.items():
            # 检查是否有精确匹配
            if clean_stage == key:
                return key

            # 检查是否包含别名
            for alias in aliases:
                if alias in clean_stage:
                    return key

        return "运维检修"  # 默认阶段

    def _get_regulation_files(self):
        """获取所有技术监督条例文件路径"""
        files = []
        for dirpath, dirnames, filenames in os.walk(self.regulations_path):
            for filename in filenames:
                if filename.endswith(('.xls', '.xlsx')) and not filename.startswith('~'):
                    files.append(os.path.join(dirpath, filename))
        return files

    def find_historical_cases_by_entities(self, entities, stage=None):
        """根据实体和可选的阶段查询历史案例"""
        results = []

        # 检索案例文件
        for file_path in self.case_files + self.transformer_files:
            try:
                if file_path.endswith('.docx') or file_path.endswith('.doc'):
                    doc = Document(file_path)
                    # 提取文档标题和内容
                    title = doc.paragraphs[0].text if doc.paragraphs else os.path.basename(file_path)
                    content = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

                    # 检查实体匹配
                    match_found = any(entity in title or entity in content for entity in entities)
                    if match_found:
                        doc_name = os.path.basename(file_path)
                        results.append({
                            "title": title,
                            "description": content[:300] + "..." if len(content) > 300 else content,
                            "source": doc_name,
                            "status": self._extract_status(content),
                            "solution": self._extract_solution(content),
                            "match_score": max(self._text_similarity(e, title + " " + content) for e in entities)
                        })
            except Exception as e:
                print(f"处理文件 {file_path} 时出错: {e}")

        # 检索问题清单表格
        for file_path in self.problem_files:
            try:
                if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
                    df = pd.read_excel(file_path)
                    # 查找问题描述和状态列
                    desc_col = next((col for col in df.columns if '问题' in col or '描述' in col), None)
                    status_col = next((col for col in df.columns if '状态' in col or '进展' in col), None)
                    solution_col = next((col for col in df.columns if '措施' in col or '解决' in col or '建议' in col),
                                        None)

                    if desc_col:
                        for _, row in df.iterrows():
                            desc = str(row.get(desc_col, ''))
                            if any(entity in desc for entity in entities):
                                status = str(row.get(status_col, '')) if status_col else '未知'
                                solution = str(row.get(solution_col, '')) if solution_col else '未提供解决方案'
                                results.append({
                                    "title": desc[:50] + "..." if len(desc) > 50 else desc,
                                    "description": desc,
                                    "source": os.path.basename(file_path),
                                    "status": status,
                                    "solution": solution,
                                    "match_score": max(self._text_similarity(e, desc) for e in entities)
                                })
            except Exception as e:
                print(f"处理文件 {file_path} 时出错: {e}")

        # 按相关性排序
        results.sort(key=lambda x: x.get('match_score', 0), reverse=True)

        return results[:15]  # 返回最相关的15条

    def _extract_status(self, text):
        """从案例文本中提取状态信息"""
        if not text:
            return "未知状态"

        if "已解决" in text or "已处理" in text or "已完成" in text:
            return "已解决"
        elif "处理中" in text or "进行中" in text:
            return "处理中"
        else:
            return "状态未明确"

    def _extract_solution(self, text):
        """从案例文本中提取解决方案"""
        if not text:
            return "未提供解决方案"

        # 尝试定位解决方案部分
        solution_patterns = ["处理措施", "解决方案", "处理方法", "解决措施", "处理建议"]
        for pattern in solution_patterns:
            if pattern in text:
                start_idx = text.find(pattern)
                end_idx = min(start_idx + 300, len(text))
                return text[start_idx:end_idx] + "..."

        return "未提供具体解决方案"

    def get_subgraph_for_entities(self, entities):
        """返回与实体相关的简单子图结构"""
        nodes = []
        links = []

        for entity in entities:
            entity_type = self._guess_entity_type(entity)
            nodes.append({
                "id": entity,
                "name": entity,
                "type": entity_type
            })

            # 创建实体间的关联
            if len(nodes) > 1:
                links.append({
                    "source": nodes[0]["id"],
                    "target": entity,
                    "relation": "相关联"
                })

        return {
            "nodes": nodes,
            "links": links
        }

    def _guess_entity_type(self, entity):
        """猜测实体类型"""
        equipment_keywords = ["变压器", "电抗器", "开关", "绝缘子", "电缆", "线路", "避雷器"]
        problem_keywords = ["渗漏油", "污闪", "缺陷", "裂纹", "老化", "破损", "异常"]

        if any(kw in entity for kw in equipment_keywords):
            return "设备"
        elif any(kw in entity for kw in problem_keywords):
            return "问题"
        else:
            return "其他"


# 创建单例
file_service = FileService()