"""
Authentication Routes - 用户注册和登录
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from datetime import datetime

bp = Blueprint('auth', __name__, url_prefix='/auth')

# Initialize extensions
bcrypt = Bcrypt()
login_manager = LoginManager()

def init_login_manager(app):
    """初始化登录管理器"""
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '请先登录'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        from core.literature_db import get_user_by_id
        return get_user_by_id(int(user_id))


@bp.route('/register', methods=['GET', 'POST'])
def register():
    """用户注册"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validation
        if not username or not email or not password:
            flash('所有字段都是必填的', 'error')
            return render_template('auth/register.html')

        if password != confirm_password:
            flash('两次输入的密码不一致', 'error')
            return render_template('auth/register.html')

        if len(password) < 6:
            flash('密码长度至少为6位', 'error')
            return render_template('auth/register.html')

        # Check if user exists
        from core.literature_db import get_user_by_username, get_user_by_email, create_user

        if get_user_by_username(username):
            flash('用户名已存在', 'error')
            return render_template('auth/register.html')

        if get_user_by_email(email):
            flash('邮箱已被注册', 'error')
            return render_template('auth/register.html')

        # Create user
        password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        success, result = create_user(username, email, password_hash, username)

        if success:
            flash('注册成功！请登录', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash(f'注册失败: {result}', 'error')
            return render_template('auth/register.html')

    return render_template('auth/register.html')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)

        if not username or not password:
            flash('用户名和密码都是必填的', 'error')
            return render_template('auth/login.html')

        from core.literature_db import get_user_by_username, update_user_last_login

        user = get_user_by_username(username)

        if user and bcrypt.check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash('账户已被禁用', 'error')
                return render_template('auth/login.html')

            login_user(user, remember=remember)
            update_user_last_login(user.id)

            next_page = request.args.get('next')
            flash(f'欢迎回来，{user.display_name or user.username}！', 'success')

            # Return JSON for AJAX login
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({
                    'success': True,
                    'message': '登录成功',
                    'next': next_page or url_for('index')
                })

            return redirect(next_page or url_for('index'))
        else:
            flash('用户名或密码错误', 'error')
            return render_template('auth/login.html')

    return render_template('auth/login.html')


@bp.route('/logout')
@login_required
def logout():
    """用户登出"""
    logout_user()
    flash('已成功登出', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/me')
def current_user_info():
    """获取当前用户信息"""
    if current_user.is_authenticated:
        return jsonify({
            'authenticated': True,
            'user': current_user.to_dict()
        })
    return jsonify({'authenticated': False})


@bp.route('/check')
def check_auth():
    """检查认证状态"""
    if current_user.is_authenticated:
        return jsonify({
            'authenticated': True,
            'username': current_user.username,
            'display_name': current_user.display_name,
            'email': current_user.email
        })
    return jsonify({'authenticated': False})
