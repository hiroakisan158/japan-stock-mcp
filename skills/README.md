# Claude Desktop スキル

このディレクトリには Claude Desktop 用のスキル定義が含まれます。

## 構成

```
skills/
├── stock-analysis/
│   └── SKILL.md        # スキル定義（編集対象）
└── stock-analysis.zip  # アップロード用 ZIP（make skill で生成）
```

## インストール

```bash
make skill
```

`skills/stock-analysis.zip` が生成されます。

Claude Desktop にアップロード：**設定 > カスタマイズ > Skills > `+` > スキルを作成 > アップロード**

## 更新

1. `stock-analysis/SKILL.md` を編集
2. `make skill` で ZIP を再生成
3. Claude Desktop で古いスキルを削除して再アップロード
