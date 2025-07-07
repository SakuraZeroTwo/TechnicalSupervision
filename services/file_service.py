# services/file_service.py
import os
import pandas as pd
import jieba
import re
from docx import Document
from services.vector_service import vector_service
from pathlib import Path
import json
import time
import csv
from typing import Set

class FileService:
    def __init__(self):
        # 基础路径配置
        self.base_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'files')
        self.regulations_path = os.path.join(self.base_path, '技术监督条例导出')
        self.cases_path = os.path.join(self.base_path, '技术监督典型案例-电科院')
        self.excel_path = os.path.join(self.base_path, '标准excel')
        self.problem_path = os.path.join(self.base_path, '技术监督问题与条例')
        self.transformer_cases_path = os.path.join(self.base_path, '甘肃电力变压器故障案例')
        self.entity_library_path = os.path.join(self.base_path, '实体库')  # 【新增】实体库路径

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

        print("FileService正在初始化...")
        # 1. 加载实体库
        self.all_known_entities = self._load_known_entities()
        self.known_entities_str = ", ".join(self.all_known_entities)
        print(f"实体库加载完成，共找到 {len(self.all_known_entities)} 个已知实体。")

        # 初始化索引
        self._build_indices()

    # 【新增】一个私有方法，专门用于加载实体库
    def _load_known_entities(self) -> Set[str]:
        """从 files/实体库/ 文件夹加载所有实体。"""
        # 使用已在__init__中定义的路径
        equipment_file = os.path.join(self.entity_library_path, '故障设备.csv')
        phenomena_file = os.path.join(self.entity_library_path, '故障现象.csv')

        entities: Set[str] = set()

        # 封装一个内部函数来读取csv，避免代码重复
        def read_csv_to_set(file_path):
            s = set()
            try:
                with open(file_path, mode='r', encoding='utf-8-sig') as infile:
                    reader = csv.reader(infile)
                    for row in reader:
                        if row and row[0].strip():
                            s.add(row[0].strip())
            except FileNotFoundError:
                print(f"    警告：实体文件未找到: {file_path}")
            return s

        equipment_entities = read_csv_to_set(equipment_file)
        phenomena_entities = read_csv_to_set(phenomena_file)

        return equipment_entities.union(phenomena_entities)

    def _find_columns_in_excel(self, file_path, sheet_name):
        """识别Excel中的关键列，处理表头在第3行的情况"""
        # 读取原始数据，不指定表头
        df_raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)

        # 定义可能的列名及其别名
        column_mappings = {
            'major_item_name': ['大项名称', '大项', '项目名称'],  # 【新增】
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

        # 尝试加载技术监督条例向量索引缓存
        if not vector_service.load_cache():
            # 如果没有缓存，则首次启动时预加载所有规范进行向量化
            print("未找到向量索引缓存，将创建新索引...")
            self._preload_regulations_for_vector_index()

        # 尝试加载历史案例向量索引缓存
        if not vector_service.load_case_cache():
            print("未找到案例向量索引缓存，将创建新索引...")
            self._preload_cases_for_vector_index()

    def _preload_regulations_for_vector_index(self):
        """预加载所有规范并创建向量索引"""
        all_regulations = []

        for file_path in self.regulation_files:
            try:
                print(f"处理文件用于向量索引: {os.path.basename(file_path)}")
                xls = pd.ExcelFile(file_path)

                for sheet_name in xls.sheet_names:
                    try:
                        column_data, _ = self._find_columns_in_excel(file_path, sheet_name)
                        if not column_data:
                            continue

                        for idx in range(len(next(iter(column_data.values())))):
                            row_data = {}
                            for col_name, col_data in column_data.items():
                                if idx < len(col_data) and pd.notna(col_data.iloc[idx]):
                                    row_data[col_name] = str(col_data.iloc[idx]).strip()

                            if row_data:
                                result = {
                                    'title': f"{os.path.basename(file_path)} - {sheet_name}",
                                    'major_item_name': row_data.get('major_item_name', ''),
                                    'basis': row_data.get('监督依据', ''),
                                    'points': row_data.get('监督要点', ''),
                                    'requirements': row_data.get('监督要求', ''),
                                    'source': {
                                        'file': os.path.basename(file_path),
                                        'sheet': sheet_name
                                    }
                                }
                                all_regulations.append(result)
                    except Exception as e:
                        print(f"处理工作表 {sheet_name} 时出错: {str(e)}")
            except Exception as e:
                print(f"处理文件 {file_path} 时出错: {str(e)}")

        # 创建向量索引
        print(f"共收集了 {len(all_regulations)} 条规范条目")
        vector_service.index_regulations(all_regulations)

    def _preload_cases_for_vector_index(self):
        """预加载所有历史案例并创建向量索引"""
        all_cases_data = []
        print("开始预加载案例文件用于向量索引...")
        for file_path in self.case_files:
            try:
                doc = Document(file_path)
                full_text = "\n".join([p.text for p in doc.paragraphs])
                title = os.path.basename(file_path)
                if doc.paragraphs and doc.paragraphs[0].text.strip():
                    title = doc.paragraphs[0].text.strip()

                if full_text.strip():
                    all_cases_data.append({
                        'text': full_text,
                        'title': title,
                        'source': os.path.basename(file_path)
                    })
            except Exception as e:
                print(f"处理案例文件 {file_path} 时出错: {e}")

        if all_cases_data:
            print(f"共收集了 {len(all_cases_data)} 个案例用于索引。")
            vector_service.index_cases(all_cases_data)
        else:
            print("未能从文件中加载任何案例数据。")
    def _scan_files(self, directory, extensions):
        """扫描指定目录下的所有符合扩展名的文件"""
        files = []
        if os.path.exists(directory):
            for root, _, filenames in os.walk(directory):
                for filename in filenames:
                    if any(filename.lower().endswith(ext) for ext in extensions) and not filename.startswith('~$'):
                        files.append(os.path.join(root, filename))
        return files

    def find_regulations_by_stage_and_keywords(self, stage, keywords, max_results=30, strict_stage_match=True,
                                               specific_file=None, use_vector_search=True):
        """根据阶段和关键词从技术监督条例中查找相关内容，增加向量搜索功能"""
        start_time = time.time()
        print(
            f"开始查询 - 阶段: {stage}, 关键词: {keywords}, 指定细则: {specific_file}, 使用向量搜索: {use_vector_search}")

        if isinstance(keywords, str):
            keywords = [keywords]

        # 优化查询文本构建，增加阶段信息提高相关性
        query_text = " ".join(keywords)
        if stage:
            query_text = f"{stage} {query_text}"

        # 如果使用向量搜索且没有指定特定文件
        if use_vector_search and not specific_file:
            # 增加检索数量，以获得更多候选结果
            vector_results = vector_service.search(query_text, keywords, top_k=max_results * 5)

            # 确保有返回结果且结构正确
            if not vector_results or not isinstance(vector_results, list):
                print("向量搜索未返回有效结果，将使用关键词搜索作为备选")
                return self.find_regulations_by_stage_and_keywords_traditional(stage, keywords, max_results,
                                                                      strict_stage_match, specific_file)

            filtered_results = []
            stage_filtered_count = 0

            for result in vector_results:
                # 允许接受更多结果，不设置相似度下限
                filtered_results.append(result)

                # 仅统计阶段匹配情况，不作为过滤条件
                if stage and strict_stage_match:
                    result_stage = result.get('stage', '')
                    source = result.get('source', {})
                    sheet_name = source.get('sheet', '')

                    # 检查阶段匹配
                    normalized_stage = self._normalize_stage(stage)
                    if (normalized_stage.lower() in sheet_name.lower() or
                            normalized_stage.lower() in result_stage.lower()):
                        stage_filtered_count += 1

            print(f"向量搜索原始结果: {len(vector_results)}条, 阶段匹配: {stage_filtered_count}条")

            # 仅当有严格阶段要求时，对结果进行阶段过滤
            if stage and strict_stage_match and stage_filtered_count > 0:
                strict_results = []
                for result in filtered_results:
                    result_stage = result.get('stage', '')
                    source = result.get('source', {})
                    sheet_name = source.get('sheet', '')

                    normalized_stage = self._normalize_stage(stage)
                    if (normalized_stage.lower() in sheet_name.lower() or
                            normalized_stage.lower() in result_stage.lower()):
                        strict_results.append(result)

                filtered_results = strict_results

            print(f"向量搜索完成，找到 {len(filtered_results)} 条匹配的规范")
            print(f"查询耗时: {time.time() - start_time:.2f}秒")
            return filtered_results[:max_results]

        # 如果指定了文件或不使用向量搜索，则回退到传统方法
        return self.find_regulations_by_stage_and_keywords_traditional(stage, keywords, max_results, strict_stage_match,
                                                              specific_file)
    def find_regulations_by_stage_and_keywords_traditional(self, stage, keywords, max_results=5, strict_stage_match=True, specific_file=None):
        """根据阶段和关键词从技术监督条例中查找相关内容"""
        results = []
        processed_files = 0
        matched_files = 0

        print(f"开始查询 - 阶段: {stage}, 关键词: {keywords}, 指定细则: {specific_file}")

        if isinstance(keywords, str):
            keywords = [keywords]

        expanded_keywords = []
        for keyword in keywords:
            expanded_keywords.append(keyword)
            if len(keyword) > 2:
                parts = jieba.lcut(keyword)
                for part in parts:
                    if len(part) >= 2 and part not in expanded_keywords:
                        expanded_keywords.append(part)

        print(f"扩展后的关键词: {expanded_keywords}")

        normalized_stage = self._normalize_stage(stage)
        print(f"标准化后的阶段: {normalized_stage}")

        # 如果指定了特定文件，只处理匹配该文件名的文件
        if specific_file:
            filtered_files = []
            for file_path in self.regulation_files:
                file_name = os.path.basename(file_path)
                if specific_file.lower() in file_name.lower():
                    filtered_files.append((file_path, 3))  # 给予更高的权重
                    print(f"找到指定细则: {file_name}")
        else:
            filtered_files = []
            for file_path in self.regulation_files:
                file_name = os.path.basename(file_path)
                if any(kw in file_name for kw in expanded_keywords):
                    filtered_files.append((file_path, 2))
                elif any(kw in file_name.lower() for kw in expanded_keywords):
                    filtered_files.append((file_path, 1))
            if not filtered_files:
                print("文件名中未找到匹配关键词的条例，将搜索所有条例文件")
                filtered_files = [(file_path, 0) for file_path in self.regulation_files]
            else:
                print(f"找到 {len(filtered_files)} 个文件名包含关键词的条例文件")

        filtered_files.sort(key=lambda x: x[1], reverse=True)

        # 如果指定了文件但没找到，返回空结果
        if specific_file and not filtered_files:
            return []

        for file_path, name_match_score in filtered_files:
            try:
                file_name = os.path.basename(file_path)
                print(f"处理文件: {file_name}" + (" (文件名匹配)" if name_match_score > 0 else ""))
                processed_files += 1
                xls = pd.ExcelFile(file_path)

                target_sheets = []
                for sheet_name in xls.sheet_names:
                    if normalized_stage.lower() in sheet_name.lower():
                        target_sheets.append(sheet_name)

                if not target_sheets and strict_stage_match:
                    continue
                elif not target_sheets:
                    target_sheets = [xls.sheet_names[0]]

                for sheet_name in target_sheets:
                    try:
                        print(f"  处理工作表: {sheet_name}")

                        # 【修正】初始化data_start_row，避免引用前未赋值的错误
                        data_start_row = 3  # 默认数据从第4行开始（索引为3）

                        column_data, col_indices = self._find_columns_in_excel(file_path, sheet_name)

                        if not column_data:
                            print(f"  工作表 {sheet_name} 未找到相关列")
                            continue

                        print(f"  在工作表 {sheet_name} 找到列: {list(column_data.keys())}")

                        for idx in range(len(next(iter(column_data.values())))):
                            row_data = {}
                            match_score = 0

                            for col_name, col_data in column_data.items():
                                if idx < len(col_data) and pd.notna(col_data.iloc[idx]):
                                    value = str(col_data.iloc[idx]).strip()
                                    row_data[col_name] = value

                                    for keyword in expanded_keywords:
                                        if keyword.lower() in value.lower():
                                            match_score += 1
                                        elif len(keyword) > 2:
                                            for part in jieba.lcut(keyword):
                                                if len(part) >= 2 and part.lower() in value.lower():
                                                    match_score += 0.5

                            match_score += name_match_score * 0.5

                            if match_score > 0:
                                title = f"{os.path.basename(file_path)} - {sheet_name}"
                                result = {
                                    'title': title,
                                    'major_item_name': row_data.get('major_item_name', ''),
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

                    except Exception as e:
                        print(f"处理工作表 {sheet_name} 时出错: {str(e)}")
                        continue
            except Exception as e:
                print(f"处理文件 {file_path} 时出错: {str(e)}")
                continue

        print(f"检索统计: 处理了{processed_files}个文件, 匹配到{matched_files}个结果")

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

    # def find_historical_cases_by_entities(self, entities, stage=None, strict_stage_match = False):
    #     """
    #     根据实体关键词和可选阶段查询历史案例文档
    #     """
    #     results = []
    #
    #     # 标准化输入
    #     if isinstance(entities, str):
    #         entities = [entities]
    #
    #     print(f"检索案例 - 关键词: {entities}, 阶段: {stage}")
    #
    #     processed_files = 0
    #     matched_files = 0
    #
    #     for file_path in self.case_files:
    #         if not file_path.endswith(('.docx', '.doc')):
    #             continue
    #
    #         try:
    #             processed_files += 1
    #             # 正确调用方法，传递文件路径而非self对象
    #             result = self.search_docx_for_keywords(file_path, entities)
    #
    #             if result:
    #                 matched_files += 1
    #                 # 如果指定了阶段，尝试进行阶段匹配
    #                 if stage and "stage" in result:
    #                     stage_match = self._match_stage(result.get("stage", ""), stage)
    #                     if not stage_match:
    #                         if strict_stage_match:
    #                             continue  # 严格模式下跳过不匹配的结果
    #                         else:
    #                             result["match_score"] *= 0.7  # 非严格模式降低分数
    #
    #                 results.append(result)
    #         except Exception as e:
    #             print(f"处理文件 {file_path} 时出错: {str(e)}")
    #
    #     print(f"检索统计: 处理了{processed_files}个文件, 匹配到{matched_files}个结果")
    #
    #     # 按匹配分数排序
    #     results.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    #
    #     # 返回前3个结果
    #     return results[:3]
    def find_historical_cases_by_entities(self, entities, stage=None, strict_stage_match=False):
        """
        【新版】根据实体关键词和可选阶段，使用向量搜索查询历史案例文档
        """
        if isinstance(entities, str):
            entities = [entities]

        # 构建查询文本
        query_text = " ".join(entities)
        if stage:
            query_text = f"{self._normalize_stage(stage)} {query_text}"

        print(f"开始向量搜索案例 - 查询: '{query_text}'")

        # 调用向量服务的案例搜索功能
        results = vector_service.search_cases(query=query_text, keywords=entities, top_k=3)

        print(f"案例向量搜索完成，找到 {len(results)} 条结果。")
        return results[:3]

    def search_docx_for_keywords(self, file_path, keywords, threshold=1):
        """
        在DOCX文档中搜索关键词，并返回匹配结果

        Args:
            file_path: DOCX文件路径
            keywords: 关键词列表或字符串
            threshold: 最小匹配数量阈值，默认为1

        Returns:
            dict: 包含匹配信息的字典，包括匹配分数、匹配到的关键词和文档信息
        """
        try:
            # 如果输入是字符串，转换为列表
            if isinstance(keywords, str):
                keywords = [keywords]

            # 打开Word文档
            doc = Document(file_path)

            # 提取所有文本
            full_text = ""
            # 从段落中提取
            for para in doc.paragraphs:
                full_text += para.text + "\n"

            # 从表格中提取
            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        full_text += cell.text + "\n"

            # 转为小写以进行不区分大小写的匹配
            full_text_lower = full_text.lower()

            # 记录匹配到的关键词
            matched_keywords = []
            for keyword in keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in full_text_lower:
                    matched_keywords.append(keyword)

            # 计算匹配分数 (匹配关键词数/总关键词数)
            match_score = len(matched_keywords) / len(keywords) if keywords else 0

            # 提取文档标题 (尝试从第一个段落或文件名获取)
            title = ""
            if doc.paragraphs and doc.paragraphs[0].text.strip():
                title = doc.paragraphs[0].text.strip()
            else:
                title = os.path.basename(file_path)

            # 提取文档描述 (尝试获取前200个字符)
            description = full_text[:200] + "..." if len(full_text) > 200 else full_text

            # 只有当匹配数量超过阈值时才认为是有效匹配
            if len(matched_keywords) >= threshold:
                return {
                    "match_score": match_score,
                    "matched_keywords": matched_keywords,
                    "match_count": len(matched_keywords),
                    "title": title,
                    "source": os.path.basename(file_path),
                }
            return None

        except Exception as e:
            print(f"处理文件 {file_path} 时出错: {str(e)}")
            return None

    def _match_stage(self, doc_stage, query_stage):
        """检查文档中的阶段是否与查询阶段匹配"""
        # 如果任一阶段为空，视为匹配
        if not doc_stage or not query_stage:
            return True

        # 标准化文档阶段
        normalized_doc_stage = self._normalize_stage(doc_stage)
        normalized_query_stage = self._normalize_stage(query_stage)

        # 比较标准化后的阶段
        return normalized_doc_stage == normalized_query_stage


# 创建单例
file_service = FileService()