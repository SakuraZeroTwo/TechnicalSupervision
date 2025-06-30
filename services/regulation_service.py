import pandas as pd
import jieba
import os
import logging

# 设置基础日志记录器
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s')


class RegulationService:
    def __init__(self, index_path='data/regulations_index.xlsx', regulations_dir='data/regulations/'):
        self.logger = logging
        try:
            from flask import current_app
            if current_app:
                self.logger = current_app.logger
        except (ImportError, RuntimeError):
            pass

        if not os.path.exists(index_path):
            self.logger.error(f"条例索引文件未找到: {index_path}")
            raise FileNotFoundError(f"条例索引文件未找到: {index_path}")

        self.index_df = pd.read_excel(index_path)
        self.regulations_dir = regulations_dir
        self.index_df['title_tokens'] = self.index_df['title'].apply(lambda x: set(jieba.cut_for_search(str(x))))

    def _find_best_matching_file(self, description: str):
        description_tokens = set(jieba.cut_for_search(description))
        scores = self.index_df['title_tokens'].apply(
            lambda title_tokens: len(description_tokens.intersection(title_tokens)))

        if scores.max() == 0:
            return None
        return self.index_df.loc[scores.idxmax()]['filename']

    def find_relevant_clauses(self, description: str, stage_name: str = None, top_n=30):
        target_filename = self._find_best_matching_file(description)
        if not target_filename:
            self.logger.info("在索引中未找到与描述匹配的文件。")
            return []

        filepath = os.path.join(self.regulations_dir, target_filename)
        if not os.path.exists(filepath):
            self.logger.error(f"错误：找到匹配文件 {target_filename}，但文件不存在于 {filepath}")
            return []

        try:
            xls = pd.ExcelFile(filepath)
            sheets_to_search = [stage_name] if stage_name and stage_name in xls.sheet_names else xls.sheet_names

            all_dfs_processed = []
            for sheet in sheets_to_search:
                # --- 终极修正：手动查找并设置表头 ---
                # 1. 读取时不指定表头，让所有行都成为数据
                df_raw = pd.read_excel(xls, sheet_name=sheet, header=None)

                header_row_index = -1
                # 2. 逐行扫描，查找哪一行包含了'监督要点'
                for i, row in df_raw.iterrows():
                    # any()会检查行中的任何一个单元格是否等于'监督要点'
                    if row.astype(str).str.contains('监督要点').any():
                        header_row_index = i
                        break

                # 3. 如果找到了表头行
                if header_row_index != -1:
                    df_processed = df_raw.copy()
                    # 将找到的行设置为新的列名
                    df_processed.columns = df_processed.iloc[header_row_index]
                    # 删除表头行及之前的所有行，只保留数据
                    df_processed = df_processed.iloc[header_row_index + 1:].reset_index(drop=True)
                    all_dfs_processed.append(df_processed)
                # --- 修正结束 ---

            if not all_dfs_processed:
                self.logger.error(f"在文件 {target_filename} 的所有工作表中都未能定位到包含'监督要点'的表头行。")
                return []

            combined_df = pd.concat(all_dfs_processed, ignore_index=True)
            search_column = '监督要点'

            if search_column not in combined_df.columns:
                # 这种情况理论上不会再发生，但作为保险
                self.logger.error(
                    f"错误：手动定位表头后，仍然无法在列名中找到 '{search_column}'。识别到的列是: {combined_df.columns.tolist()}")
                return []

            combined_df.dropna(subset=[search_column], inplace=True)
            combined_df['search_tokens'] = combined_df[search_column].astype(str).apply(
                lambda x: set(jieba.cut_for_search(x)))

            description_tokens = set(jieba.cut_for_search(description))
            scores = combined_df['search_tokens'].apply(
                lambda search_tokens: len(description_tokens.intersection(search_tokens)))

            if scores.max() == 0:
                self.logger.info(f"在文件 {target_filename} 的 '{search_column}' 列中没有匹配到任何相关内容。")
                return []

            top_indices = scores.nlargest(top_n).index
            return combined_df.loc[top_indices].drop(columns=['search_tokens']).to_dict('records')

        except Exception as e:
            self.logger.error(f"处理Excel文件 {filepath} 时发生未知错误: {e}")
            return []


# 创建单例的逻辑保持不变
try:
    from flask import current_app

    if current_app:
        regulation_service = RegulationService()
    else:
        regulation_service = None
except (ImportError, RuntimeError):
    regulation_service = None