import os
from neo4j import GraphDatabase

class Neo4jService:
    def __init__(self):
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USER")
        password = os.getenv("NEO4J_PASSWORD")
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self._driver.close()

    def execute_query(self, query, parameters=None):
        """通用查询执行函数"""
        with self._driver.session() as session:
            result = session.run(query, parameters)
            return [record for record in result]

    def find_historical_cases(self, keyword: str):
        """根据关键词检索历史案例"""
        # 这是一个示例查询，你需要根据你的图数据模型进行调整
        query = """
        MATCH (c:Case)
        WHERE c.description CONTAINS $keyword OR c.analysis CONTAINS $keyword
        RETURN c.id as id, c.description as description, c.date as date
        LIMIT 10
        """
        return self.execute_query(query, {"keyword": keyword})

    def get_subgraph_for_entities(self, entities: list):
        """
        根据实体列表（如：['油污', '绝缘子']）返回相关子图
        """
        # 这个查询会返回与实体直接相关的节点和关系
        query = """
        MATCH (n)
        WHERE n.name IN $entities
        CALL apoc.path.subgraphAll(n, {
            maxLevel: 1
        })
        YIELD nodes, relationships
        RETURN nodes, relationships
        """
        # 注意: 上述查询需要安装 APOC 插件。
        # 在 Neo4j Desktop 中，选择你的数据库 -> "Plugins" -> "APOC" -> "Install"。
        return self.execute_query(query, {"entities": entities})

# 创建一个单例，方便在应用中复用
neo4j_service = Neo4jService()
