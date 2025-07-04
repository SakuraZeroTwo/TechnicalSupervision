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
        try:
            print("正在加载向量模型: 尝试从模型库加载")
            model_candidates = [
                "shibing624/text2vec-base-chinese",
                "moka-ai/m3e-small",
                "cyclone/simcse-chinese-roberta-wwm-ext"
            ]
            for model_name in model_candidates:
                try:
                    self.model = SentenceTransformer(model_name)
                    self.model_name = model_name
                    print(f"成功加载模型: {model_name}")
                    break
                except Exception as e:
                    print(f"尝试加载模型 {model_name} 失败: {e}")

            if not hasattr(self, 'model'):
                local_model_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'models', 'text2vec-base')
                if os.path.exists(local_model_path):
                    print(f"尝试从本地加载模型: {local_model_path}")
                    self.model = SentenceTransformer(local_model_path)
                    self.model_name = "本地模型"
                else:
                    raise ValueError("无法加载向量模型，请确保模型已下载或网络连接正常")
        except Exception as e:
            print(f"向量模型加载失败: {e}")
            self.model = None
            self.model_name = "fallback"

        # 初始化代码
        self.index = None
        self.metadata = []
        self.texts = []

        # TF-IDF 相关初始化
        self.tfidf_vectorizer = None
        self.tfidf_matrix = None

        # 缓存相关配置
        self.cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache')
        os.makedirs(self.cache_dir, exist_ok=True)
        self.index_file = os.path.join(self.cache_dir, 'faiss_index.bin')
        self.metadata_file = os.path.join(self.cache_dir, 'metadata.pkl')
        self.texts_file = os.path.join(self.cache_dir, 'texts.pkl')
        # TF-IDF 缓存路径
        self.tfidf_vectorizer_file = os.path.join(self.cache_dir, 'tfidf_vectorizer.pkl')
        self.tfidf_matrix_file = os.path.join(self.cache_dir, 'tfidf_matrix.pkl')

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