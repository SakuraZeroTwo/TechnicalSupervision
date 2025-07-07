import os
import jieba
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
import pickle
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# 定义一个顶层函数用于jieba分词，以允许pickle序列化
def jieba_tokenizer(text):
    """使用jieba进行分词"""
    return jieba.lcut(text)

def get_key(item):
    return item['score']

class VectorService:
    def __init__(self):
        # 检查是否有可用的GPU
        self.device = 'cuda' if faiss.get_num_gpus() > 0 else 'cpu'
        print(f"向量服务正在使用: {self.device}")

        # --- 修改开始 ---
        # 从本地路径加载模型
        # 首先获取当前文件所在的目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # 构建模型的绝对路径 (假设 models 文件夹在项目根目录)
        model_path = os.path.join(current_dir, '..', 'models', 'shibing624/text2vec-base-chinese')

        # 检查模型路径是否存在
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"模型文件夹未在预期路径找到: {model_path}。请确认您已下载模型并放置在正确位置。"
            )

        self.model = SentenceTransformer(model_path, device=self.device)

        # 初始化代码
        self.index = None
        self.metadata = []
        self.texts = []

        # TF-IDF 相关初始化
        self.tfidf_vectorizer = None
        self.tfidf_matrix = None

        # 历史案例相关初始化
        self.case_index = None
        self.case_metadata = []
        self.case_texts = []
        self.case_tfidf_vectorizer = None
        self.case_tfidf_matrix = None

        # 缓存相关配置
        self.cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache')
        os.makedirs(self.cache_dir, exist_ok=True)
        self.index_file = os.path.join(self.cache_dir, 'faiss_index.bin')
        self.metadata_file = os.path.join(self.cache_dir, 'metadata.pkl')
        self.texts_file = os.path.join(self.cache_dir, 'texts.pkl')
        # TF-IDF 缓存路径
        self.tfidf_vectorizer_file = os.path.join(self.cache_dir, 'tfidf_vectorizer.pkl')
        self.tfidf_matrix_file = os.path.join(self.cache_dir, 'tfidf_matrix.pkl')

        # 历史案例缓存配置
        self.case_index_file = os.path.join(self.cache_dir, 'case_faiss_index.bin')
        self.case_metadata_file = os.path.join(self.cache_dir, 'case_metadata.pkl')
        self.case_texts_file = os.path.join(self.cache_dir, 'case_texts.pkl')
        self.case_tfidf_vectorizer_file = os.path.join(self.cache_dir, 'case_tfidf_vectorizer.pkl')
        self.case_tfidf_matrix_file = os.path.join(self.cache_dir, 'case_tfidf_matrix.pkl')

    def index_regulations(self, regulations):
        """为规范条例创建向量索引和TF-IDF矩阵"""
        print(f"开始为 {len(regulations)} 条规范创建索引...")

        texts = []
        metadata = []
        for reg in regulations:
            content = f"{reg.get('title', '')} {reg.get('basis', '')} {reg.get('points', '')} {reg.get('requirements', '')}"
            texts.append(content)
            metadata.append(reg)

        self.texts = texts
        self.metadata = metadata

        # 1. 创建语义向量索引 (FAISS)
        if self.model:
            vectors = self.encode(texts)
            faiss.normalize_L2(vectors)
            dimension = self.model.get_sentence_embedding_dimension()
            self.index = faiss.IndexFlatIP(dimension)
            self.index.add(np.array(vectors).astype('float32'))
            print("语义向量索引创建完成。")
        else:
            print("警告：未加载语义模型，语义搜索将不可用。")

        # 2. 创建关键词索引 (TF-IDF)
        # 使用具名函数替换lambda函数，以解决pickle错误
        self.tfidf_vectorizer = TfidfVectorizer(tokenizer=jieba_tokenizer)
        self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(self.texts)
        print("TF-IDF关键词索引创建完成。")

        # 3. 缓存到本地
        self._save_cache()
        print(f"索引创建完成，包含 {len(texts)} 条规范")
        return True

    def index_cases(self, cases_data):
        """为历史案例文档创建向量索引和TF-IDF索引"""
        if not cases_data:
            print("没有提供案例数据用于索引。")
            return False

        print(f"开始为 {len(cases_data)} 个案例创建索引...")
        self.case_texts = [case['text'] for case in cases_data]
        self.case_metadata = [{'source': case['source'], 'title': case['title']} for case in cases_data]

        # 1. 创建并保存 TF-IDF 索引
        self.case_tfidf_vectorizer = TfidfVectorizer(tokenizer=jieba_tokenizer)
        self.case_tfidf_matrix = self.case_tfidf_vectorizer.fit_transform(self.case_texts)

        # 2. 创建并保存 Faiss 向量索引
        embeddings = self.encode(self.case_texts)
        if embeddings.size == 0:
            print("案例向量化失败，索引未创建。")
            self.case_index = None
            return False

        d = embeddings.shape[1]
        self.case_index = faiss.IndexFlatL2(d)
        self.case_index.add(embeddings)

        # 3. 保存缓存
        try:
            # 保存Faiss索引
            faiss.write_index(self.case_index, self.case_index_file)
            # 保存元数据和文本
            with open(self.case_metadata_file, 'wb') as f:
                pickle.dump(self.case_metadata, f)
            with open(self.case_texts_file, 'wb') as f:
                pickle.dump(self.case_texts, f)
            # 保存TF-IDF模型和矩阵
            with open(self.case_tfidf_vectorizer_file, 'wb') as f:
                pickle.dump(self.case_tfidf_vectorizer, f)
            with open(self.case_tfidf_matrix_file, 'wb') as f:
                pickle.dump(self.case_tfidf_matrix, f)
            print("案例索引和缓存已成功保存。")
        except Exception as e:
            print(f"保存案例缓存时出错: {e}")
            return False
        return True

    def search(self, query, keywords, top_k=5, threshold=0.1):
        """
        混合搜索：结合TF-IDF关键词匹配和语义相似度。
        最终分数 = 0.7 * TF-IDF分数 + 0.3 * 语义分数
        """
        if not self.texts:
            print("错误: 索引未初始化。")
            return []

        # 1. 【计算TF-IDF关键词分数】
        keyword_query = " ".join(keywords)
        query_tfidf_vector = self.tfidf_vectorizer.transform([keyword_query])
        tfidf_scores = cosine_similarity(query_tfidf_vector, self.tfidf_matrix).flatten()

        # 2. 【计算语义分数】
        semantic_scores = np.zeros(len(self.texts))
        if self.index and self.model:
            query_vector = self.encode(query)
            if query_vector.ndim == 1:
                query_vector = np.expand_dims(query_vector, axis=0)
            faiss.normalize_L2(query_vector)
            query_vector = query_vector.astype('float32')
            # 检索比top_k更多的结果，以便后续融合排序
            distances, indices = self.index.search(query_vector, len(self.texts))

            # 创建一个从文档ID到分数的映射
            for i, doc_id in enumerate(indices[0]):
                if doc_id != -1:
                    semantic_scores[doc_id] = distances[0][i]

        # 3. 【加权融合分数】
        keyword_weight = 0.7
        semantic_weight = 0.3

        # 如果语义搜索不可用，则将所有权重分配给关键词
        if not self.model or not self.index:
            keyword_weight = 1.0
            semantic_weight = 0.0

        final_scores = (keyword_weight * tfidf_scores) + (semantic_weight * semantic_scores)

        # 4. 【排序和返回结果】
        # 获取得分最高的 top_k*2 个索引（为阈值过滤留出余量）
        top_indices = np.argsort(final_scores)[-top_k * 2:][::-1]

        results = []
        for idx in top_indices:
            final_score = final_scores[idx]
            if final_score >= threshold:
                meta = self.metadata[idx]
                result_item = {
                    'title': meta['source']['file'],
                    'major_item_name': meta.get('major_item_name', ''),
                    'supervision_number': meta.get('supervision_number', ''),
                    'basis': meta.get('basis', ''),
                    'points': meta.get('points', ''),
                    'requirements': meta.get('requirements', ''),
                    'source': meta['source'],
                    'score': float(final_score),  # 返回最终的综合分数
                    'tfidf_score': float(tfidf_scores[idx]),
                    'semantic_score': float(semantic_scores[idx])
                }
                results.append(result_item)

        # 按综合分数再次排序并截取top_k
        results.sort(key=get_key, reverse=True)

        print(f"混合搜索完成，返回 {len(results[:top_k])} 条结果。")
        return results[:top_k]

    def search_cases(self, query, keywords, top_k=3):
        """使用混合搜索在历史案例中进行检索"""
        if not self.case_texts or self.case_tfidf_vectorizer is None:
            print("案例索引未加载或为空，无法搜索。")
            return []

        # 1. TF-IDF 分数
        keyword_query = " ".join(keywords)
        query_tfidf = self.case_tfidf_vectorizer.transform([keyword_query])
        tfidf_scores = cosine_similarity(query_tfidf, self.case_tfidf_matrix).flatten()

        # 2. 语义分数
        semantic_scores = np.zeros(len(self.case_texts))
        if self.case_index and self.model:
            query_embedding = self.encode([query])
            if query_embedding.size > 0:
                _, I = self.case_index.search(query_embedding, len(self.case_texts))
                # 简单的基于排名的分数
                for i, idx in enumerate(I[0]):
                    semantic_scores[idx] = 1.0 - (i / len(self.case_texts))

        # 3. 混合分数
        final_scores = (0.7 * tfidf_scores) + (0.3 * semantic_scores)

        # 4. 排序和返回
        top_indices = np.argsort(final_scores)[-top_k:][::-1]
        results = []
        for idx in top_indices:
            results.append({
                'title': self.case_metadata[idx]['title'],
                'source': self.case_metadata[idx]['source'],
                'score': final_scores[idx]
            })
        return results

    def _save_cache(self):
        """将所有索引和相关数据保存到本地"""
        try:
            # 保存FAISS索引
            if self.index:
                faiss.write_index(self.index, self.index_file)
            # 保存元数据和文本
            with open(self.metadata_file, 'wb') as f:
                pickle.dump(self.metadata, f)
            with open(self.texts_file, 'wb') as f:
                pickle.dump(self.texts, f)
            # 保存TF-IDF模型和矩阵
            if self.tfidf_vectorizer:
                with open(self.tfidf_vectorizer_file, 'wb') as f:
                    pickle.dump(self.tfidf_vectorizer, f)
            if self.tfidf_matrix is not None:
                with open(self.tfidf_matrix_file, 'wb') as f:
                    pickle.dump(self.tfidf_matrix, f)

            print(f"所有索引已缓存到: {self.cache_dir}")
        except Exception as e:
            print(f"缓存索引时出错: {e}")

    def load_cache(self):
        """从缓存加载所有索引"""
        # 检查所有必要的缓存文件是否存在
        faiss_ready = os.path.exists(self.index_file)
        tfidf_ready = os.path.exists(self.tfidf_vectorizer_file) and os.path.exists(self.tfidf_matrix_file)

        if not (faiss_ready and tfidf_ready and os.path.exists(self.metadata_file) and os.path.exists(self.texts_file)):
            print("部分缓存文件缺失，将重新构建索引。")
            return False

        try:
            # 加载FAISS
            self.index = faiss.read_index(self.index_file)
            # 加载元数据和文本
            with open(self.metadata_file, 'rb') as f:
                self.metadata = pickle.load(f)
            with open(self.texts_file, 'rb') as f:
                self.texts = pickle.load(f)
            # 加载TF-IDF
            with open(self.tfidf_vectorizer_file, 'rb') as f:
                self.tfidf_vectorizer = pickle.load(f)
            with open(self.tfidf_matrix_file, 'rb') as f:
                self.tfidf_matrix = pickle.load(f)

            print(f"从缓存加载所有索引，包含 {len(self.texts)} 条规范")
            return True
        except Exception as e:
            print(f"加载缓存索引时出错: {e}")
            return False

    def load_case_cache(self):
        """从缓存加载案例索引"""
        if not all(os.path.exists(f) for f in [self.case_index_file, self.case_metadata_file, self.case_texts_file, self.case_tfidf_vectorizer_file, self.case_tfidf_matrix_file]):
            print("案例索引缓存文件不完整，将跳过加载。")
            return False
        try:
            self.case_index = faiss.read_index(self.case_index_file)
            with open(self.case_metadata_file, 'rb') as f:
                self.case_metadata = pickle.load(f)
            with open(self.case_texts_file, 'rb') as f:
                self.case_texts = pickle.load(f)
            with open(self.case_tfidf_vectorizer_file, 'rb') as f:
                self.case_tfidf_vectorizer = pickle.load(f)
            with open(self.case_tfidf_matrix_file, 'rb') as f:
                self.case_tfidf_matrix = pickle.load(f)
            print(f"成功从缓存加载 {len(self.case_metadata)} 个案例索引。")
            return True
        except Exception as e:
            print(f"加载案例缓存时出错: {e}")
            return False
    def encode(self, texts):
        """对文本进行向量化"""
        if self.model:
            return self.model.encode(texts, show_progress_bar=False)
        # 如果模型加载失败，返回一个空数组或根据需要处理
        if isinstance(texts, list):
            return np.array([[] for _ in texts])
        return np.array([])




# 创建单例
vector_service = VectorService()