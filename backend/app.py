import os
import hashlib
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from datetime import datetime, timedelta
from functools import wraps

# 環境変数をロード (開発環境用)
load_dotenv()

app = Flask(__name__)

# データベースURIを環境変数から設定
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 運営者IDを環境変数から取得 (デフォルト値を設定)
OPERATOR_ID = os.environ.get('OPERATOR_ID', 'default_operator_id_for_dev')

# 権限レベルの定義 (低い方から順に)
ROLES = ['青ID', 'スピーカー', 'マネージャー', 'モデレーター', 'サミット', '運営']

# 連投対策のクールダウンタイム (秒)
COOLDOWN_SECONDS = 5

# --- ヘルパー関数とデコレータ ---
def get_role_level(role_name):
    """ロール名からレベル (インデックス) を取得する"""
    try:
        return ROLES.index(role_name)
    except ValueError:
        return -1 # 未定義のロール

def get_current_user_role():
    """現在のリクエストを行っているユーザーのロールを返す (仮の実装)"""
    # **重要**: 本番環境では、実際の認証システム (JWT, セッションなど) から
    # ユーザー情報を取得し、そのロールを返すように実装してください。
    # ここでは、X-User-Role ヘッダーを一時的に使用します。
    return request.headers.get('X-User-Role', '青ID')

def role_required(min_role_name):
    """指定された最低限のロールを持つユーザーのみアクセスを許可するデコレータ"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            current_user_role = get_current_user_role()
            if get_role_level(current_user_role) < get_role_level(min_role_name):
                return jsonify({'error': f'権限が不足しています。{min_role_name}以上の権限が必要です。'}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# --- データベースモデル定義 ---
class User(db.Model):
    """ユーザー情報を格納するモデル"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128)) # ログイン用パスワードのハッシュ (今は使わないが将来用)
    role = db.Column(db.String(20), default='青ID') # 権限レベル
    is_killed = db.Column(db.Boolean, default=False) # /kill コマンド用
    is_banned = db.Column(db.Boolean, default=False) # /ban コマンド用 (アカウントBAN)
    additional_text = db.Column(db.String(100), nullable=True) # /add コマンド用
    display_color = db.Column(db.String(7), default='#000000') # /color コマンド用 (今は使わないが将来用)
    last_post_time = db.Column(db.DateTime, nullable=True) # 連投対策用

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'

class Post(db.Model):
    """掲示板の投稿を格納するモデル"""
    id = db.Column(db.Integer, primary_key=True) # 投稿Noとして利用
    name = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, nullable=False)
    password_hash = db.Column(db.String(64), nullable=True) # 投稿パスワードのSHA-256ハッシュ
    created_at = db.Column(db.DateTime, default=db.func.now())
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # 投稿者 (Userモデルと紐付け)
    user = db.relationship('User', backref='posts') # Userモデルへのリレーション
    parent_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True) # 返信元投稿のID
    children = db.relationship('Post', backref=db.backref('parent', remote_side=[id]), lazy=True) # 返信 (子投稿) へのリレーション

    def __repr__(self):
        return f'<Post {self.id}: {self.name}>'

    def to_dict(self):
        """投稿データをJSONシリアライズ可能な辞書形式で返す"""
        # パスワードハッシュの最初の7文字を取得
        hash_seven_chars = self.password_hash[:7] if self.password_hash else '0000000'

        # /add コマンドで追加された文字を結合
        full_name = self.name
        if self.user and self.user.additional_text:
            full_name = f"{self.name}{self.user.additional_text}" # 名前<追加文字> ではなく、名前追加文字 に変更

        # ユーザーが存在すればそのロールを取得、なければ「青ID」
        user_role = self.user.role if self.user else '青ID'

        return {
            'no': self.id,
            'name': f"{full_name}@{hash_seven_chars}", # 表示用の名前とハッシュ
            'raw_name': self.name, # 追加文字なしの元の名前
            'additional_text': self.user.additional_text if self.user else None, # 追加文字自体
            'content': self.content,
            'time': self.created_at.strftime('%Y-%m-%d %H:%M:%S'), # 時間のフォーマット
            'parent_id': self.parent_id, # 返信元ID
            'user_role': user_role # ユーザーの権限
        }

# --- データベースの初期化 ---
with app.app_context():
    db.create_all() # アプリケーション起動時にテーブルを作成/更新

# --- APIエンドポイント ---
@app.route('/posts', methods=['GET'])
def get_posts():
    """全ての投稿を取得するAPI"""
    # 投稿と関連するユーザー情報を一緒に取得する (N+1問題回避)
    posts = Post.query.options(db.joinedload(Post.user)).order_by(Post.created_at.desc()).all()
    return jsonify([p.to_dict() for p in posts])

@app.route('/posts', methods=['POST'])
def add_post():
    """新しい投稿を追加するAPI"""
    data = request.json
    name = data.get('name')
    content = data.get('content')
    raw_password = data.get('password', '')
    parent_id = data.get('parent_id', None) # 返信元投稿のID

    if not name or not content:
        return jsonify({'error': '名前と内容は必須です。'}), 400

    # ユーザーの取得または新規作成
    user = User.query.filter_by(username=name).first()
    if not user:
        # 新規ユーザー作成時に初期ロールを設定
        user = User(username=name, password_hash=hashlib.sha256("dummy_initial_password".encode('utf-8')).hexdigest(), role="青ID")
        db.session.add(user)
        db.session.commit() # ユーザーIDを確定させるためにコミット

    # 連投チェック
    if user.last_post_time:
        time_since_last_post = datetime.now() - user.last_post_time
        if time_since_last_post.total_seconds() < COOLDOWN_SECONDS:
            remaining_time = COOLDOWN_SECONDS - int(time_since_last_post.total_seconds())
            return jsonify({'error': f'連投は禁止されています。あと {remaining_time} 秒待ってください。'}), 429 # Too Many Requests

    # 投稿パスワードのSHA-256ハッシュを計算
    sha256_hash = hashlib.sha256(raw_password.encode('utf-8')).hexdigest()

    # 新しい投稿を作成
    new_post = Post(name=name, content=content, password_hash=sha256_hash, user_id=user.id, parent_id=parent_id)
    db.session.add(new_post)
    
    # ユーザーの最終投稿時刻を更新
    user.last_post_time = datetime.now()
    
    db.session.commit()
    db.session.refresh(new_post) # リレーションシップをロードするためにリフレッシュ
    return jsonify({'message': '投稿が追加されました！', 'post': new_post.to_dict()}), 201

# --- コマンド処理のメインエンドポイント ---
@app.route('/command', methods=['POST'])
@role_required('モデレーター') # コマンドはモデレーター以上の権限が必要な例
def handle_command():
    """コマンドを受け付けて処理するAPI"""
    data = request.json
    full_command_text = data.get('command')

    if not full_command_text or not full_command_text.startswith('/'):
        return jsonify({'error': '無効なコマンド形式です。コマンドは "/" から始めてください。'}), 400

    # コマンドを解析: /command arg1 arg2 ...
    parts = full_command_text.split(' ', 2) # コマンド名、引数1、残りの引数(文字列結合用)
    command = parts[0][1:] # '/' を除くコマンド名

    # 各コマンドの処理に分岐
    if command == 'add':
        # 使用方法: /add (ID) (IDの後ろにつけたい文字)
        if len(parts) < 3:
            return jsonify({'error': '使用方法: /add (ID) (IDの後ろにつけたい文字)'}), 400
        target_username = parts[1]
        text_to_add = parts[2]
        return add_text_to_user(target_username, text_to_add)
    
    elif command == 'del':
        # /del (投稿番号) のように指定 (一括削除対応)
        if len(parts) < 2:
            return jsonify({'error': '使用方法: /del (投稿番号) [投稿番号...]'})
        post_ids = [int(p) for p in parts[1:] if p.isdigit()]
        return delete_posts_by_id(post_ids)

    elif command == 'destroy':
        # /destroy (文字) (例: /destroy (color)blue)
        if len(parts) < 2:
            return jsonify({'error': '使用方法: /destroy (文字) または /destroy (color)blue'})
        
        target_criteria = parts[1]
        if target_criteria.startswith('(color)'):
            color_name = target_criteria[len('(color)'):]
            # ここで color_name に対応するロールを取得し、そのロールのユーザーの投稿を削除するロジック
            # 現時点では色とロールの厳密なマッピングがないため、仮の実装
            return jsonify({'message': f'カラー "{color_name}" による削除は現在未実装です。'}), 501
        else:
            # 特定の文字が含まれる投稿を削除
            return delete_posts_by_content(target_criteria)

    elif command == 'clear':
        # 全ての投稿を削除
        return clear_all_posts()

    # --- 他のコマンドも同様に分岐して処理関数を呼び出す ---
    # 例: 権限昇格/降格
    elif command in ROLES: # 例: /スピーカー user1, /マネージャー user2
        if len(parts) < 2:
            return jsonify({'error': f'使用方法: /{command} (ID)'}), 400
        target_username = parts[1]
        return promote_demote_user_role(target_username, command)
    elif command.startswith('dis') and command[3:] in ROLES: # 例: /disspeaker user1
        if len(parts) < 2:
            return jsonify({'error': f'使用方法: /{command} (ID)'}), 400
        target_username = parts[1]
        # ロール降格は逆順に処理
        target_role = command[3:]
        return promote_demote_user_role(target_username, target_role, demote=True)
    elif command == 'disself':
        # 自身の権限を青IDに降格
        # ここではユーザー認証がないため、request.headers.get('X-User-Name')などからユーザー名を特定
        current_username = request.headers.get('X-User-Name', name) # 仮のユーザー名取得
        return promote_demote_user_role(current_username, '青ID') # 自分自身を青IDに

    # NG/OK コマンドなどは別途テーブルが必要なので、ここでは未実装メッセージ
    elif command == 'NG' or command == 'OK':
        return jsonify({'message': f'{command} コマンドは未実装です。NGワード管理機能が必要です。'}), 501
    elif command in ['prevent', 'permit', 'restrict', 'stop', 'prohibit', 'release']:
        return jsonify({'message': f'{command} コマンドは未実装です。規制管理機能が必要です。'}), 501
    elif command in ['kill', 'ban', 'revive']:
        return jsonify({'message': f'{command} コマンドは未実装です。ユーザー状態管理機能が必要です。'}), 501
    elif command in ['reduce', 'topic', 'color', 'instances', 'max', 'range']:
        return jsonify({'message': f'{command} コマンドは未実装です。'}), 501

    else:
        return jsonify({'error': f'不明なコマンドです: /{command}'}), 400

# --- コマンドの具体的な処理関数 ---

@role_required('モデレーター')
def add_text_to_user(username, text_to_add):
    """/add コマンドの処理: ユーザーに文字を追加する"""
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': f'ユーザー "{username}" が見つかりません。'}), 404

    user.additional_text = text_to_add
    db.session.commit()
    return jsonify({'message': f'ユーザー "{username}" に文字 "{text_to_add}" を追加しました。'}), 200

@role_required('マネージャー')
def delete_posts_by_id(post_ids):
    """/del コマンドの処理: 指定されたIDの投稿を削除する"""
    if not post_ids:
        return jsonify({'error': '削除する投稿番号を指定してください。'}), 400
    
    deleted_count = 0
    for post_id in post_ids:
        post = db.session.get(Post, post_id)
        if post:
            db.session.delete(post)
            deleted_count += 1
    db.session.commit()
    return jsonify({'message': f'{deleted_count} 件の投稿を削除しました。'}), 200

@role_required('モデレーター')
def delete_posts_by_content(keyword):
    """/destroy コマンドの処理: 特定のキーワードが含まれる投稿を削除する"""
    if not keyword:
        return jsonify({'error': '削除するキーワードを指定してください。'}), 400
    
    # 部分一致で検索
    posts_to_delete = Post.query.filter(Post.content.like(f'%{keyword}%')).all()
    deleted_count = 0
    for post in posts_to_delete:
        db.session.delete(post)
        deleted_count += 1
    db.session.commit()
    return jsonify({'message': f'キーワード "{keyword}" を含む {deleted_count} 件の投稿を削除しました。'}), 200

@role_required('モデレーター')
def clear_all_posts():
    """/clear コマンドの処理: 全ての投稿を削除し、IDをリセットする"""
    try:
        # PostgreSQL の TRUNCATE TABLE は ID シーケンスもリセットする
        # SQLite の場合は VACUUM も必要かもしれない
        db.session.execute(db.text('TRUNCATE TABLE post RESTART IDENTITY CASCADE'))
        db.session.commit()
        return jsonify({'message': '全ての投稿を削除し、投稿番号をリセットしました。'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'全ての投稿の削除に失敗しました: {str(e)}'}), 500

@role_required('サミット') # 昇格/降格はサミット以上が可能な例
def promote_demote_user_role(username, target_role_name, demote=False):
    """権限昇格/降格コマンドの処理"""
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': f'ユーザー "{username}" が見つかりません。'}), 404

    current_role_level = get_role_level(user.role)
    target_role_level = get_role_level(target_role_name)
    
    # コマンド実行者の権限レベルを取得 (ここでは仮に運営とするが、実際は認証されたユーザーのロール)
    commander_role_level = get_role_level(get_current_user_role()) # 例: '運営' -> 5

    # 昇格の場合
    if not demote:
        if target_role_level <= current_role_level:
            return jsonify({'error': f'ユーザー "{username}" は既に同等以上の権限 "{user.role}" を持っています。'}), 400
        # 付与できる権限:付与できるようになる権限 のロジックをここに実装
        # 例: スピーカー(1)はマネージャー(2)まで付与可能
        if target_role_level - 1 > commander_role_level : # コマンド実行者より2段階以上高い権限は付与不可
             return jsonify({'error': '付与できる権限レベルを超えています。'}), 403

        user.role = target_role_name
        db.session.commit()
        return jsonify({'message': f'ユーザー "{username}" の権限を "{target_role_name}" に昇格しました。'}), 200
    
    # 降格の場合
    else:
        if target_role_level >= current_role_level:
            return jsonify({'error': f'ユーザー "{username}" は既に同等以下の権限 "{user.role}" です。'}), 400
        # 降格させる権限:降格できるようになる権限 のロジックをここに実装
        # 例: マネージャー(2)はモデレーター(3)に降格できる (ロールレベルが上がる)
        # 自身より高い権限のユーザーは降格させられない、など
        if target_role_level + 1 < commander_role_level : # コマンド実行者より2段階以上低い権限は降格不可
             return jsonify({'error': '降格できる権限レベルを超えています。'}), 403

        user.role = target_role_name
        db.session.commit()
        return jsonify({'message': f'ユーザー "{username}" の権限を "{target_role_name}" に降格しました。'}), 200

# --- アプリケーションの実行 ---
if __name__ == '__main__':
    # 開発サーバーの実行 (Render デプロイ時は Gunicorn を使用)
    app.run(debug=True, host='0.0.0.0', port=os.environ.get('PORT', 5000))
