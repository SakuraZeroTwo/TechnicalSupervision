import pandas as pd
import jieba
import os
from flask import current_app


class RegulationService:
    def __init__(self, index_path='data/regulations_index.xlsx', regulations_dir='data/regulations/'):
        """
        初始化时加载条例索引文件。
        """
        if not os.path.exists(index_path):
            raise FileNotFoundError(f"条例索引文件未找到: {index_path}")
        self.index_df = pd.read_excel(index_path)
        self.regulations_dir = regulations_dir
        # 预先对所有标题进行分词
        self.index_df['title_tokens'] = self.index_df['title'].apply(lambda x: set(jieba.cut_for_search(str(x))))

    def _find_best_matching_file(self, description: str):
        """
        [私有方法] 根据描述在索引中找到最匹配的一个文件名。
        """
        description_tokens = set(jieba.cut_for_search(description))
        scores = self.index_df['title_tokens'].apply(
            lambda title_tokens: len(description_tokens.intersection(title_tokens)))

        if scores.max() == 0:
            return None

        best_index = scores.idxmax()
        return self.index_df.loc[best_index]['filename']

    def find_relevant_clauses(self, description: str, stage_name: str = None, top_n=30):
        """
        根据输入描述，在最匹配的条例文件中检索出最相关的细则。

        Args:
            description (str): 用户输入的问题描述。
            stage_name (str, optional): 前端传入的阶段名，对应Excel的Sheet名。 Defaults to None.
            top_n (int): 返回最匹配的细则数量。

        Returns:
            list: 包含最匹配细则的字典列表。
        """
        # 1. 粗筛：找到最匹配的条例文件
        target_filename = self._find_best_matching_file(description)
        if not target_filename:
            return []

        filepath = os.path.join(self.regulations_dir, target_filename)
        if not os.path.exists(filepath):
            current_app.logger.error(f"找到匹配文件 {target_filename}，但文件不存在于 {filepath}")
            return []

        try:
            xls = pd.ExcelFile(filepath)
            all_sheets = xls.sheet_names

            # 2. 确定要检索的Sheet范围
            sheets_to_search = []
            if stage_name and stage_name in all_sheets:
                sheets_to_search = [stage_name]
            else:
                # 如果没有提供阶段或阶段不存在，则搜索所有Sheet
                sheets_to_search = all_sheets

            # 3. 读取并合并数据
            df_list = []
            for sheet in sheets_to_search:
                df_sheet = pd.read_excel(xls, sheet_name=sheet)
                df_list.append(df_sheet)

            if not df_list:
                return []

            combined_df = pd.concat(df_list, ignore_index=True)

            # --- 关键列名，如果您的列名不同，请在这里修改 ---
            search_column = '监督要点'
            # ----------------------------------------------

            if search_column not in combined_df.columns:
                current_app.logger.error(f"文件 {target_filename} 中未找到列: '{search_column}'")
                return []

            # 4. 精筛：在选定数据范围内进行内容匹配
            # 清理空值并确保是字符串类型
            combined_df.dropna(subset=[search_column], inplace=True)
            combined_df['search_tokens'] = combined_df[search_column].astype(str).apply(
                lambda x: set(jieba.cut_for_search(x)))

            description_tokens = set(jieba.cut_for_search(description))
            scores = combined_df['search_tokens'].apply(
                lambda search_tokens: len(description_tokens.intersection(search_tokens)))

            if scores.max() == 0:
                return []

            # 5. 返回得分最高的 top_n 条细则
            top_indices = scores.nlargest(top_n).index
            # 去掉临时添加的 'search_tokens' 列，并转换为字典列表返回
            results = combined_df.loc[top_indices].drop(columns=['search_tokens']).to_dict('records')

            return results

        except Exception as e:
            current_app.logger.error(f"处理Excel文件 {filepath} 时出错: {e}")
            return []


# 创建一个单例，方便在应用中复用
regulation_service = RegulationService()