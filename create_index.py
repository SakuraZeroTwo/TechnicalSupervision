# create_index.py

import os
import pandas as pd

# --- 配置 ---
# 1. 请将所有条例的 .xls 文件放入这个文件夹
regulations_folder = 'data/regulations'

# 2. 这是生成的索引文件的保存路径
output_path = 'data/regulations_index.xlsx'


# --- 配置结束 ---


def create_regulation_index():
    """
    扫描指定文件夹中的条例文件，并创建一个Excel索引文件。
    索引文件包含两列：'title' (不含扩展名的文件名) 和 'filename' (完整文件名)。
    """

    # 检查条例文件夹是否存在
    if not os.path.exists(regulations_folder):
        print(f"错误：文件夹 '{regulations_folder}' 不存在。")
        print("请先创建该文件夹，并将所有条例 .xls 文件放入其中。")
        return

    # 获取文件夹下所有 .xls 和 .xlsx 文件
    files = [f for f in os.listdir(regulations_folder) if f.endswith(('.xls', '.xlsx'))]

    if not files:
        print(f"警告：在文件夹 '{regulations_folder}' 中没有找到任何 .xls 或 .xlsx 文件。")
        return

    print(f"找到了 {len(files)} 个条例文件。正在生成索引...")

    # 创建一个列表来存储文件信息
    index_data = []
    for filename in files:
        # 去掉文件扩展名作为 title
        title = os.path.splitext(filename)[0]
        index_data.append({
            'title': title,
            'filename': filename
        })

    # 将列表转换为 pandas DataFrame
    df = pd.DataFrame(index_data)

    # 确保输出目录存在
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 将 DataFrame 保存为 Excel 文件
    df.to_excel(output_path, index=False)

    print(f"成功！索引文件已保存至: {output_path}")
    print("\n索引内容预览:")
    print(df.head())


if __name__ == '__main__':
    create_regulation_index()