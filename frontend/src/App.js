import React, { useState, useEffect, useRef } from 'react';

// APIのベースURL。Renderデプロイ時は環境変数から取得
const API_BASE_URL = process.env.REACT_APP_API_BASE_URL || 'http://localhost:5000';

// 権限ごとの色定義
const ROLE_COLORS = {
    '青ID': 'blue',
    'スピーカー': 'darkorange',
    'モデレーター': 'purple',
    'マネージャー': 'red',
    'サミット': 'darkcyan',
    '運営': 'red' // 運営は名前が赤
};

// 連投対策のクールダウンタイム (秒) - バックエンドと合わせる
const COOLDOWN_DURATION = 5;

function App() {
    const [posts, setPosts] = useState([]); // 投稿リスト
    const [name, setName] = useState(''); // 投稿フォームの名前
    const [content, setContent] = useState(''); // 投稿フォームの内容
    const [password, setPassword] = useState(''); // 投稿フォームのパスワード
    const [commandInput, setCommandInput] = useState(''); // コマンド入力
    const [replyingTo, setReplyingTo] = useState(null); // 返信対象の投稿No

    // 連投対策用のState
    const [isCoolingDown, setIsCoolingDown] = useState(false); // クールダウン中か
    const [remainingCooldown, setRemainingCooldown] = useState(0); // 残りクールダウン時間
    const cooldownTimerRef = useRef(null); // タイマーIDを保持するためのref

    // 初回レンダリング時とアンマウント時の処理
    useEffect(() => {
        fetchPosts(); // 投稿をフェッチ

        // コンポーネントアンマウント時にタイマーをクリア
        return () => {
            if (cooldownTimerRef.current) {
                clearInterval(cooldownTimerRef.current);
            }
        };
    }, []);

    // クールダウンタイマーを開始する関数
    const startCooldownTimer = () => {
        setIsCoolingDown(true);
        setRemainingCooldown(COOLDOWN_DURATION);

        // 既存のタイマーがあればクリア
        if (cooldownTimerRef.current) {
            clearInterval(cooldownTimerRef.current);
        }

        // 新しいタイマーを設定
        cooldownTimerRef.current = setInterval(() => {
            setRemainingCooldown(prev => {
                if (prev <= 1) { // 残り時間が1秒以下になったらタイマーを停止
                    clearInterval(cooldownTimerRef.current);
                    setIsCoolingDown(false);
                    return 0;
                }
                return prev - 1; // 1秒減らす
            });
        }, 1000); // 1秒ごとに実行
    };

    // 投稿リストを取得する関数
    const fetchPosts = async () => {
        try {
            const response = await fetch(`${API_BASE_URL}/posts`);
            const data = await response.json();
            setPosts(data);
        } catch (error) {
            console.error('Error fetching posts:', error);
            alert('投稿の取得に失敗しました。');
        }
    };

    // 投稿フォームの送信ハンドラ
    const handleSubmitPost = async (e) => {
        e.preventDefault();

        // クールダウン中の場合は投稿を拒否
        if (isCoolingDown) {
            alert(`連投は禁止されています。あと ${remainingCooldown} 秒待ってください。`);
            return;
        }

        try {
            const postData = {
                name,
                content,
                password,
                parent_id: replyingTo // 返信対象のIDがあれば含める
            };
            const response = await fetch(`${API_BASE_URL}/posts`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(postData),
            });
            const data = await response.json();
            if (response.ok) {
                alert(data.message);
                setPosts([data.post, ...posts]); // 新しい投稿をリストの先頭に追加
                setName('');
                setContent('');
                setPassword('');
                setReplyingTo(null); // 返信モードを終了
                startCooldownTimer(); // 投稿成功時にクールダウン開始
            } else {
                alert(data.error);
                // バックエンドから連投エラーが返された場合もクールダウンを開始
                if (response.status === 429 && data.error.includes('連投は禁止されています')) {
                    startCooldownTimer();
                }
            }
        } catch (error) {
            console.error('Error creating post:', error);
            alert('投稿に失敗しました。');
        }
    };

    // コマンドフォームの送信ハンドラ
    const handleSubmitCommand = async (e) => {
        e.preventDefault();
        // コマンドは "/" から始まる必要がある
        if (!commandInput.startsWith('/')) {
            alert('コマンドは "/" から始めてください。');
            return;
        }

        // コマンドを解析し、削除系コマンドかチェック
        const commandParts = commandInput.split(' ');
        const commandName = commandParts[0].substring(1); // '/' を除くコマンド名

        const destructiveCommands = ['del', 'destroy', 'clear']; // 削除系コマンドのリスト

        // 削除系コマンドの場合は確認プロンプトを表示
        if (destructiveCommands.includes(commandName)) {
            const confirmMessage = `本当に "${commandInput}" を実行して投稿を削除しますか？\nこの操作は取り消せません。`;
            if (!window.confirm(confirmMessage)) {
                alert('コマンドの実行をキャンセルしました。');
                return; // ユーザーがキャンセルした場合、処理を中断
            }
        }

        try {
            const response = await fetch(`${API_BASE_URL}/command`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    // **重要**: ここは仮の権限ヘッダーです。
                    // 実際にはログインしたユーザーの権限を動的に設定する必要があります。
                    'X-User-Role': '運営', // コマンド実行者の権限を仮で「運営」とする
                    'X-User-Name': 'テスト運営者' // 仮のユーザー名 (disselfなどで使用)
                },
                body: JSON.stringify({ command: commandInput }),
            });
            const data = await response.json();
            if (response.ok) {
                alert(data.message);
                setCommandInput(''); // コマンド入力欄をクリア
                fetchPosts(); // 変更が反映されるように投稿を再フェッチ
            } else {
                alert(`コマンドエラー: ${data.error}`);
            }
        } catch (error) {
            console.error('コマンド実行エラー:', error);
            alert('コマンドの実行中にエラーが発生しました。');
        }
    };

    return (
        <div>
            <h1>掲示板</h1>

            {/* 投稿フォーム */}
            <form onSubmit={handleSubmitPost}>
                {/* 返信モード時の表示 */}
                {replyingTo && (
                    <p style={{ fontWeight: 'bold', color: '#333' }}>
                        No.{replyingTo} への返信{' '}
                        <button type="button" onClick={() => setReplyingTo(null)} style={{ marginLeft: '10px', padding: '5px 10px' }}>
                            返信をやめる
                        </button>
                    </p>
                )}
                <input
                    type="text"
                    placeholder="名前"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                />
                <br />
                <textarea
                    placeholder="投稿内容"
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    required
                ></textarea>
                <br />
                <input
                    type="password"
                    placeholder="投稿用パスワード"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                />
                <br />
                {/* 投稿ボタン (クールダウン中は無効化) */}
                <button type="submit" disabled={isCoolingDown} style={{ padding: '10px 20px', fontSize: '16px' }}>
                    投稿
                    {/* クールダウン中であれば残り時間を表示 */}
                    {isCoolingDown && ` (${remainingCooldown}s)`}
                </button>
                {/* クールダウン中のメッセージ */}
                {isCoolingDown && (
                    <p style={{ color: 'red', fontSize: '0.9em', marginTop: '5px' }}>連投できません。しばらくお待ちください。</p>
                )}
            </form>

            <hr style={{ margin: '30px 0' }} />

            {/* コマンド入力フォーム */}
            <h2>コマンド入力</h2>
            <form onSubmit={handleSubmitCommand}>
                <input
                    type="text"
                    placeholder="/add user text, /del 1 2, /destroy keyword など"
                    value={commandInput}
                    onChange={(e) => setCommandInput(e.target.value)}
                    style={{ width: '400px', padding: '8px', marginRight: '10px' }}
                />
                <button type="submit" style={{ padding: '8px 15px' }}>コマンド実行</button>
            </form>

            <hr style={{ margin: '30px 0' }} />

            <h2>投稿一覧</h2>
            <div>
                {posts.map((post) => {
                    // 投稿番号のスタイルを決定 (権限による色分け)
                    const noStyle = {};
                    if (post.user_role && post.user_role !== '運営') {
                        noStyle.color = ROLE_COLORS[post.user_role] || 'inherit';
                    }

                    // 名前のスタイルを決定 (運営は名前が赤)
                    const nameStyle = {
                        color: post.user_role === '運営' ? 'red' : 'inherit'
                    };

                    return (
                        <div key={post.no} style={{ border: '1px solid #ddd', margin: '15px 0', padding: '15px', borderRadius: '8px', backgroundColor: '#f9f9f9' }}>
                            {/* 返信元表示 */}
                            {post.parent_id && (
                                <p style={{ fontSize: '0.8em', color: '#666', marginBottom: '5px' }}>
                                    返信元: No.{post.parent_id}
                                </p>
                            )}
                            <p>
                                <strong>No:</strong>{' '}
                                {/* 運営以外はNoに色を付ける。運営は「IDなし」と表示 */}
                                {post.user_role === '運営' ? (
                                    <span style={{ color: '#888' }}>IDなし</span>
                                ) : (
                                    <span style={noStyle}>{post.no}</span>
                                )}
                            </p>
                            <p>
                                <strong>名前:</strong>{' '}
                                <span style={nameStyle}>
                                    {post.raw_name}
                                    {/* /add コマンドで追加された文字 (マゼンタ色) */}
                                    {post.additional_text && (
                                        <span style={{ color: 'magenta' }}>
                                            {post.additional_text}
                                        </span>
                                    )}
                                    {/* パスワードハッシュの最初の7文字 */}
                                    @{post.name.split('@')[1]}
                                </span>
                            </p>
                            <p><strong>投稿:</strong> {post.content}</p>
                            <p style={{ fontSize: '0.9em', color: '#777' }}><strong>時間:</strong> {post.time}</p>
                            {/* 返信ボタン */}
                            <button onClick={() => setReplyingTo(post.no)} style={{ marginTop: '10px', padding: '8px 12px' }}>返信</button>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export default App;
