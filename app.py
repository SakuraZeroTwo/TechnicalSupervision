from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import os

# 在应用启动时加载 .env 文件
load_dotenv()

def create_app():
    app = Flask(__name__)

    # 【重要】启用CORS，允许所有来源的跨域请求
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # 确保上传目录存在
    upload_folder = os.path.join('static', 'uploads')
    reports_folder = os.path.join('static', 'reports')

    for folder in [upload_folder, reports_folder]:
        if not os.path.exists(folder):
            os.makedirs(folder)
    app.config['UPLOAD_FOLDER'] = upload_folder

    # 创建一个简单的内存缓存
    app.cache = {}

    # 从 api.routes 模块中导入并注册蓝图
    from api.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.route('/')
    def index():
        return "后端服务已启动！"

    return app

if __name__ == '__main__':
    app = create_app()
    # Debug 模式会在代码变动后自动重启服务
    app.run(debug=True, port=5000)