from flask import Flask, jsonify
from dotenv import load_dotenv
import os

# 在应用启动时加载 .env 文件
load_dotenv()

def create_app():
    app = Flask(__name__)

    # 确保上传目录存在
    upload_folder = os.path.join('static', 'uploads')
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)
    app.config['UPLOAD_FOLDER'] = upload_folder

    # 从 api.routes 模块中导入并注册蓝图
    from api.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.route('/')
    def index():
        return "后端服务已启动！"

    # 注册一个应用关闭时的钩子，来关闭 Neo4j 连接
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        from services.neo4j_service import neo4j_service
        # Neo4jService 类中没有 close 方法，所以我们不能调用它
        # 如果需要，可以在 Neo4jService 中添加一个 close 方法
        pass

    return app

if __name__ == '__main__':
    app = create_app()
    # Debug 模式会在代码变动后自动重启服务
    app.run(debug=True, port=5000)
