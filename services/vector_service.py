import os

import jieba
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
import torch
import pickle
from pathlib import Path


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

            # 如果所有在线模型都失败，尝试本地路径
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
            print("将使用简单的词频向量化替代方案")
            self.model = None
            self.model_name = "fallback-tfidf"

        # 初始化代码
        self.vector_dim = 768  # 默认向量维度
        self.index = None
        self.id_to_text_mapping = {}

        # 缓存相关配置
        self.cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache')
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        self.index_cache_path = os.path.join(self.cache_dir, 'faiss_index.bin')
        self.mapping_cache_path = os.path.join(self.cache_dir, 'id_text_mapping.json')

        # 添加这些属性以匹配load_cache和_save_cache方法使用的名称
        self.index_file = os.path.join(self.cache_dir, 'faiss_index.bin')
        self.texts_file = os.path.join(self.cache_dir, 'texts.pkl')
        self.metadata_file = os.path.join(self.cache_dir, 'metadata.pkl')

    def index_regulations(self, regulations):
        """为规范条例创建向量索引"""
        print(f"开始为 {len(regulations)} 条规范创建向量索引...")

        texts = []
        metadata = []

        for reg in regulations:
            # 组合规范的关键部分，提高语义匹配效果
            content = f"{reg.get('title', '')} {reg.get('basis', '')} {reg.get('points', '')} {reg.get('requirements', '')}"
            texts.append(content)
            metadata.append(reg)

        # 编码文本向量
        vectors = self.encode(texts)

        # 对向量进行归一化
        faiss.normalize_L2(vectors)

        # 创建FAISS索引
        dimension = self.model.get_sentence_embedding_dimension()
        self.index = faiss.IndexFlatIP(dimension)  # 使用内积（余弦相似度）
        self.index.add(np.array(vectors).astype('float32'))

        # 保存文本和元数据
        self.texts = texts
        self.metadata = metadata

        # 创建索引到元数据的映射
        self.id_to_text_mapping = {}
        for i, meta in enumerate(metadata):
            self.id_to_text_mapping[str(i)] = meta

        # 缓存到本地
        self._save_cache()

        print(f"向量索引创建完成，包含 {len(texts)} 条规范")
        return True

    def search(self, query, top_k=5, threshold=0.1):
        """搜索最相似的规范条目"""
        if not self.index:
            print("错误: 向量索引未初始化。")
            return []

        try:
            # 1. 将查询文本编码为向量
            query_vector = self.encode(query)
            if query_vector.ndim == 1:
                query_vector = np.expand_dims(query_vector, axis=0)

            # 对查询向量进行归一化
            faiss.normalize_L2(query_vector)

            # 确保向量是 float32 类型
            query_vector = query_vector.astype('float32')

            # 2. 在FAISS索引中执行搜索
            # D是距离/相似度分数，I是匹配项的索引
            distances, indices = self.index.search(query_vector, top_k)

            # 3. 处理并返回结果
            results = []
            # indices[0] 包含与第一个（也是唯一一个）查询向量匹配的 top_k 个结果的ID
            for i in range(len(indices[0])):
                idx = indices[0][i]
                score = distances[0][i]

                # 如果索引ID无效（例如为-1），则跳过
                if idx == -1:
                    continue

                # 根据阈值过滤结果
                if score >= threshold:
                    # 从元数据中获取原始信息
                    meta = self.metadata[idx]
                    result_item = {
                        'title': meta['source']['file'],
                        'major_item_name': meta.get('major_item_name', ''),
                        'basis': meta.get('basis', ''),
                        'points': meta.get('points', ''),
                        'requirements': meta.get('requirements', ''),
                        'source': meta['source'],
                        'score': float(score)  # 返回相似度分数
                    }
                    results.append(result_item)

            print(f"向量搜索原始结果数量: {len(indices[0])}")
            if len(distances[0]) > 0:
                print(f"过滤前的最高相似度: {distances[0][0]:.4f}")
            print(f"过滤后的结果数量: {len(results)}")

            return results

        except Exception as e:
            print(f"向量搜索时发生错误: {e}")
            return []

    def _save_cache(self):
        """将索引和相关数据保存到本地"""
        try:
            faiss.write_index(self.index, self.index_file)

            with open(self.texts_file, 'wb') as f:
                pickle.dump(self.texts, f)

            with open(self.metadata_file, 'wb') as f:
                pickle.dump(self.metadata, f)

            print(f"向量索引已缓存到: {self.cache_dir}")
        except Exception as e:
            print(f"缓存索引时出错: {e}")

    def load_cache(self):
        """从缓存加载索引"""
        if (os.path.exists(self.index_file) and
                os.path.exists(self.texts_file) and
                os.path.exists(self.metadata_file)):
            try:
                self.index = faiss.read_index(self.index_file)

                with open(self.texts_file, 'rb') as f:
                    self.texts = pickle.load(f)

                with open(self.metadata_file, 'rb') as f:
                    self.metadata = pickle.load(f)

                # 重建索引到元数据的映射
                self.id_to_text_mapping = {}
                for i, meta in enumerate(self.metadata):
                    self.id_to_text_mapping[str(i)] = meta

                print(f"从缓存加载向量索引，包含 {len(self.texts)} 条规范")
                return True
            except Exception as e:
                print(f"加载缓存索引时出错: {e}")
        return False

    def _simple_encode(self, texts):
        """当模型加载失败时的简单向量化方法"""
        if not isinstance(texts, list):
            texts = [texts]

        vectors = []
        for text in texts:
            # 使用jieba分词
            words = jieba.lcut(text)
            # 创建一个简单的词袋向量
            vec = np.zeros(self.vector_dim)
            for i, word in enumerate(words):
                # 使用词的位置和长度生成简单的数值表示
                val = len(word) / (i + 1)
                idx = hash(word) % self.vector_dim
                vec[idx] += val
            # 归一化向量
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectors.append(vec)

        return np.array(vectors)

    def encode(self, texts):
        """对文本进行向量化，结合词频特征(0.7)和语义特征(0.3)"""
        try:
            if not isinstance(texts, list):
                texts = [texts]

            # 1. 获取语义向量 (使用预训练模型)
            if self.model:
                semantic_vectors = self.model.encode(texts, show_progress_bar=False)
            else:
                # 如果没有预训练模型，使用备用方法
                semantic_vectors = self._simple_encode(texts)

            # 2. 生成词频向量
            tfidf_vectors = self._generate_tfidf_vectors(texts)

            # 3. 按权重合并向量 (词频0.7，语义0.3)
            combined_vectors = []
            for i in range(len(texts)):
                # 确保向量维度一致
                if tfidf_vectors[i].shape[0] != semantic_vectors[i].shape[0]:
                    # 如果维度不一致，将两个向量调整为相同维度
                    dim = min(tfidf_vectors[i].shape[0], semantic_vectors[i].shape[0])
                    tf_vec = tfidf_vectors[i][:dim]
                    sem_vec = semantic_vectors[i][:dim]
                else:
                    tf_vec = tfidf_vectors[i]
                    sem_vec = semantic_vectors[i]

                # 按权重合并
                combined = 0.7 * tf_vec + 0.3 * sem_vec

                # 归一化
                norm = np.linalg.norm(combined)
                if norm > 0:
                    combined = combined / norm

                combined_vectors.append(combined)

            return np.array(combined_vectors)

        except Exception as e:
            print(f"向量化过程出错: {e}")
            # 出错时回退到简单方法
            return self._simple_encode(texts)

    def _generate_tfidf_vectors(self, texts):
        """生成基于词频的向量表示"""
        vectors = []

        # 统计所有文档中的词汇
        all_words = {}
        for text in texts:
            words = jieba.lcut(text)
            for word in words:
                if word not in all_words:
                    all_words[word] = 0
                all_words[word] += 1

        # 词汇表大小
        vocab_size = len(all_words)
        if vocab_size == 0:
            return np.zeros((len(texts), self.vector_dim))

        # 计算IDF值
        doc_count = len(texts)
        word_idf = {}
        for word, count in all_words.items():
            word_idf[word] = np.log(doc_count / count)

        # 为每个文档生成TF-IDF向量
        for text in texts:
            # 计算词频
            word_counts = {}
            words = jieba.lcut(text)
            for word in words:
                if word not in word_counts:
                    word_counts[word] = 0
                word_counts[word] += 1

            # 生成向量
            vec = np.zeros(self.vector_dim)
            for word, count in word_counts.items():
                # 计算TF-IDF值
                tf = count / len(words)
                idf = word_idf.get(word, 0)
                tfidf = tf * idf

                # 使用哈希将词映射到向量维度
                idx = hash(word) % self.vector_dim
                vec[idx] += tfidf

            # 归一化
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm

            vectors.append(vec)

        return np.array(vectors)
# 创建单例
vector_service = VectorService()