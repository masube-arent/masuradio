# 2026-11-10 MASURADIO 出典確認メモ・条件補強版

## 完了した修正

- GitHub章：Enterprise Cloudに加えSecret ProtectionまたはAdvanced Securityが必要、ポリシーは既定無効、有効化後かつシークレットスキャン有効リポジトリの新規実行が対象、と明記。検査は実行完了後。引用語数の枠を契約と適用条件へ振り替えたため、通知なしという話題は削除した。
- Drive章：バナー変更の説明を短縮し、先行・計画的リリースとも今月9日から段階展開、最大15日かかると追記。適用条件の繰り返しだった後半を展開時期の説明に置き換えた。
- Skills章：管理者がアクセスを制御するという条件を追加。契約プランが対象か、社内で利用が許可されているかを先に確認する運用を推奨した。英語の指示・プロンプトのみ、Sheets/Meet非対応の制約は保持した。
- DX章：Driveの権限説明を一般的な検索全体ではなく「ラベル検索」に限定した。対象・作業・確認・中止の完全一致文字列を保持した。
- validate_package(data, '2026-11-10') は正常終了。意味の校閲と音声確認は別途必要。

## 確認した公式本文と短い忠実な抜粋

原文引用は各出典25語以内。短い句や節も含むため、引用だけですべての条件の正しさを証明する資料ではない。以下の公式本文を独立校閲で読み、発話の条件・制約まで照合すること。

1. https://workspaceupdates.googleblog.com/2026/11/skills-in-workspace.html
   - 原文引用21語。対応アプリと言語の条件。
   - 一覧の表示日は11月9日、個別記事の表示日は11月10日。article_published_date は個別記事に合わせた。発話では公開日を断定しない。
   - 本文 Availability に対象プランが列挙されている。発話では全プラン利用可能とは言わず、契約を確認するよう勧める。
2. https://support.google.com/workspace-studio/answer/17307546
   - 原文引用21語。管理者のアクセス制御とスキルの基本定義。公開日表示なしのため null。
   - 管理者によるアクセス制御の抜粋は原文の後続にある外部共有の制御を省いた短い主節。外部共有を自由に行えるとの主張はしていない。
3. https://github.blog/changelog/2026-11-09-secret-scanning-detects-secrets-in-github-actions-workflow-logs/
   - 原文引用24語。How do I enable it? 節の対象契約と既定無効の主節。
   - 本文は対象契約についてGHE.comのデータ所在地対応も含むと続くが、音声ではそれを説明していない。除外する主張もしていない。
   - 本文にある有効化手順は実行していない。設定変更を実施したとの説明もない。
4. https://docs.github.com/en/enterprise-cloud@latest/code-security/concepts/secret-security/secret-scanning
   - 原文引用22語。有効化後の新規実行、実行完了後、シークレットスキャン有効リポジトリ、という条件を含む完全な文。
   - 同じ節の直後には過去の実行ログを検査しないと明記されている。発話も過去ログを検査済みと扱わない内容に限定。
5. https://workspaceupdates.googleblog.com/2026/11/quickly-confirm-system-applied-classification-labels-in-Google-Drive-Docs-Sheets-and-Slides.html
   - 原文引用22語。バナーのボタン表示を表す短い抜粋と、段階展開の期間・開始日の案内。
   - 本文冒頭は「単一の自動適用ラベル」「変更権限を持つ利用者」を条件としている。抜粋だけでは省かれている条件を、日本語のsection_headingと発話で保持した。
   - Rollout pace はRapid ReleaseとScheduled Release両方。November 9, 2026 と up to 15 days が正確な原文根拠。日本語の発話は「今月9日」「最大15日」。
6. https://support.google.com/drive/answer/13495216
   - 原文引用9語。Search for files with labels 節にあるアクセス権限の条件をDX章で使用。
   - ラベルそのものがアクセス権を与えるという主張はしていない。

## 編集・実行範囲

ニュースは3本、reportの出典URLは5つ。各出典に2つの発話セグメントを対応付けた。最後の活用提案は架空の案件メモを使う週報下書きの検証手順であり、実証した生産性向上や精度改善ではない。引用を別章へ重複掲載していない。

この担当で変更した成果物は script.json とこのメモのみ。公開、音声生成、GitHub変更、再生速度変更は実行していない。時間と英語製品名の読みは実音声で確認すること。
