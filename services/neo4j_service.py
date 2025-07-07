import os
from neo4j import GraphDatabase
import traceback
import json
import random


class Neo4jService:
    def __init__(self):
        """
        初始化Neo4j驱动程序，从环境变量中读取配置。
        """
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USER")
        password = os.getenv("NEO4J_PASSWORD")

        if not all([uri, user, password]):
            print("警告: Neo4j 环境变量未完全设置，图数据库服务将不可用。")
            self._driver = None
        else:
            self._driver = GraphDatabase.driver(uri, auth=(user, password), database="neo4j-i")

    def close(self):
        """
        关闭数据库驱动连接。
        """
        if self._driver:
            self._driver.close()

    def _format_subgraph_result(self, records):
        """
        健壮的格式化函数，用于将多个查询结果合并并去重。
        """
        nodes = {}
        links = set()

        def get_node_name(node_obj):
            return node_obj.get('name') or node_obj.get('名称') or node_obj.get('title') or 'Unnamed'

        for record in records:
            for key in record.keys():
                item = record[key]
                if item is None:
                    continue

                if hasattr(item, 'nodes') and hasattr(item, 'relationships'):
                    for node in item.nodes:
                        if node.element_id not in nodes:
                            nodes[node.element_id] = {"id": node.element_id, "name": get_node_name(node),
                                                      "type": list(node.labels)[0] if node.labels else "Unknown"}
                    for rel in item.relationships:
                        links.add((rel.start_node.element_id, rel.end_node.element_id, rel.type))

                elif hasattr(item, 'labels'):
                    if item.element_id not in nodes:
                        nodes[item.element_id] = {"id": item.element_id, "name": get_node_name(item),
                                                  "type": list(item.labels)[0] if item.labels else "Unknown"}

                elif hasattr(item, 'type') and hasattr(item, 'start_node') and hasattr(item, 'end_node'):
                    start_node, end_node = item.start_node, item.end_node
                    if start_node.element_id not in nodes:
                        nodes[start_node.element_id] = {"id": start_node.element_id, "name": get_node_name(start_node),
                                                        "type": list(start_node.labels)[
                                                            0] if start_node.labels else "Unknown"}
                    if end_node.element_id not in nodes:
                        nodes[end_node.element_id] = {"id": end_node.element_id, "name": get_node_name(end_node),
                                                      "type": list(end_node.labels)[
                                                          0] if end_node.labels else "Unknown"}
                    links.add((start_node.element_id, end_node.element_id, item.type))

        final_nodes = list(nodes.values())
        final_links = [{"source": l[0], "target": l[1], "relation": l[2]} for l in links]

        return {"nodes": final_nodes, "links": final_links}

    def get_subgraph_for_entities(self, entities: list, k: int = 2, max_length: int = 5):
        """
        【生产版】: 使用最终优化的组合查询策略，并包含完整的邻居和路径查找。
        """
        if not self._driver:
            return {"nodes": [], "links": [], "error": "Neo4j 服务未初始化。"}
        if not entities:
            return {"nodes": [], "links": []}

        # 恢复 all_records 列表
        all_records = []
        try:
            with self._driver.session() as session:
                # 步骤 1: 使用组合查询策略查找最相关的代表节点
                find_reps_query = """
                   UNWIND $entities AS entityName
                   CALL {
                       WITH entityName
                       // 优先级1: 精确匹配
                       MATCH (n) WHERE n.name = entityName
                       RETURN n, 1 AS priority
                       LIMIT 1
                   UNION
                       WITH entityName
                       // 优先级2: 包含匹配
                       MATCH (n) WHERE n.name CONTAINS entityName
                       RETURN n, 2 AS priority
                       LIMIT 1
                   UNION
                       WITH entityName
                       // 优先级3: 模糊匹配 (阈值可以按需调整，例如0.5或0.85)
                       MATCH (n)
                       WITH n, apoc.text.jaroWinklerDistance(n.name, entityName) AS score
                       WHERE score > 0.5
                       RETURN n, 3 AS priority
                       ORDER BY score DESC
                       LIMIT 1
                   }
                   // 按 entityName 分组，为每个实体独立筛选最优结果
                   WITH entityName, n, priority
                   ORDER BY priority ASC
                   WITH entityName, head(collect(n)) as best_node
                   RETURN best_node AS representative
                   """

                reps_result = session.run(find_reps_query, {"entities": entities})
                representative_nodes = [record["representative"] for record in reps_result if
                                        record["representative"] is not None]

                if not representative_nodes:
                    return {"nodes": [], "links": [], "message": "未能根据实体名称找到任何相似的代表节点。"}

                rep_ids = [node.element_id for node in representative_nodes]
                # 将代表节点自身先加入到记录中，以便在没有邻居和路径时也能显示
                all_records.extend([{"node": node} for node in representative_nodes])

                # 步骤 2: 【已恢复】基于确切的代表节点ID，查找它们的随机邻居
                neighbor_query = """
                   UNWIND $ids AS repId
                   MATCH (n) WHERE elementId(n) = repId
                   MATCH (n)-[r]-(m)
                   WITH n, r, m, rand() as random_order
                   ORDER BY random_order
                   WITH n, type(r) as rel_type, collect({relation: r, neighbor: m}) as items
                   UNWIND items[..$k] as sampled_item
                   RETURN n, sampled_item.relation AS r, sampled_item.neighbor AS m
                   """
                neighbor_result = session.run(neighbor_query, {"ids": rep_ids, "k": k})
                all_records.extend([record for record in neighbor_result])

                # 步骤 3: 【已恢复】基于确切的代表节点ID，查找它们之间的所有路径
                if len(rep_ids) > 1:
                    path_query_template = """
                       MATCH (n) WHERE elementId(n) IN $ids
                       WITH collect(n) AS nodes
                       UNWIND nodes AS n1
                       UNWIND nodes AS n2
                       WITH n1, n2 WHERE elementId(n1) < elementId(n2)
                       MATCH p = allShortestPaths((n1)-[*..{max_length}]-(n2))
                       RETURN p
                       LIMIT 5
                       """
                    path_query = path_query_template.format(max_length=max_length)
                    path_result = session.run(path_query, {"ids": rep_ids})
                    all_records.extend([record for record in path_result])

                # 如果只有代表节点，没有邻居和路径，也能正确返回
                if not all_records:
                    return {"nodes": [], "links": [], "message": "在图数据库中未找到任何匹配的实体或其关系。"}

                return self._format_subgraph_result(all_records)

        except Exception as e:
            print(f"Neo4j 查询失败: {e}")
            traceback.print_exc()
            return {"nodes": [], "links": [], "error": str(e)}


# 创建一个单例
neo4j_service = Neo4jService()