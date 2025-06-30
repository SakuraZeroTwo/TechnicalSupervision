import sys
import os
import pprint  # 引入pprint，让打印结果更好看

# 将项目根目录添加到Python的模块搜索路径中
# 这允许我们导入项目中的模块，比如 services.regulation_service
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from services.regulation_service import RegulationService


def run_test():
    """
    执行检索服务的隔离测试。
    """
    print("--- 开始测试 RegulationService ---")

    # 1. 定义你要测试的输入描述
    # TODO: 请在这里修改为你想要测试的关键词，例如 "变压器", "油污", "绝缘子" 等
    test_description = "变压器"
    print(f"\n[测试输入] 问题描述: '{test_description}'")

    try:
        # 2. 手动实例化服务
        # 注意：这里的路径是相对于项目根目录的
        service = RegulationService(
            index_path='data/regulations_index.xlsx',
            regulations_dir='data/regulations/'
        )
        print("[状态] RegulationService 实例化成功。")

        # 3. 调用核心函数
        results = service.find_relevant_clauses(test_description, top_n=5)
        print("[状态] find_relevant_clauses 函数调用完成。")

        # 4. 打印结果
        if results:
            print(f"\n[测试输出] 成功找到 {len(results)} 条相关细则：")
            pprint.pprint(results)
        else:
            print("\n[测试输出] 未找到任何相关细则。请检查：")
            print("  - 'data/regulations_index.xlsx' 文件中是否有与关键词匹配的'title'。")
            print("  - 对应的细则文件中，是否存在名为'监督要点'的列。")
            print("  - '监督要点'列的内容是否与您的关键词相关。")

    except FileNotFoundError as e:
        print(f"\n[致命错误] 文件未找到: {e}")
        print("请确保测试脚本位于项目根目录，并且'data'文件夹路径正确。")
    except Exception as e:
        print(f"\n[程序异常] 测试过程中发生错误: {e}")

    print("\n--- 测试结束 ---")


if __name__ == '__main__':
    # 当直接运行此脚本时，执行测试函数
    run_test()