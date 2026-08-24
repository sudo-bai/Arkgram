#!/usr/bin/env bash
set -euo pipefail

# Arkgram Android signing keystore generator.
# Fill these values, or provide them through environment variables.
KEYSTORE_PASS="${KEYSTORE_PASS:-}"
KEY_ALIAS="${KEY_ALIAS:-arkgram}"
ALIAS_PASS="${ALIAS_PASS:-}"

# Set FORCE_OVERWRITE=yes only when you intentionally want to replace a key.
FORCE_OVERWRITE="${FORCE_OVERWRITE:-no}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_KEYSTORE="${OUTPUT_KEYSTORE:-$PROJECT_ROOT/TMessagesProj/release.keystore}"

if ! command -v keytool >/dev/null 2>&1; then
    printf '错误：找不到 keytool，请先安装 JDK。\n' >&2
    exit 1
fi

if [[ -z "$KEYSTORE_PASS" ]]; then
    read -r -s -p '请输入 KEYSTORE_PASS（签名库密码）: ' KEYSTORE_PASS
    printf '\n'
fi
if [[ -z "$ALIAS_PASS" ]]; then
    read -r -s -p '请输入 ALIAS_PASS（密钥密码）: ' ALIAS_PASS
    printf '\n'
fi

if [[ -z "$KEYSTORE_PASS" || -z "$ALIAS_PASS" || -z "$KEY_ALIAS" ]]; then
    printf '错误：KEYSTORE_PASS、KEY_ALIAS、ALIAS_PASS 都不能为空。\n' >&2
    exit 1
fi

if [[ -e "$OUTPUT_KEYSTORE" && "$FORCE_OVERWRITE" != 'yes' ]]; then
    printf '错误：目标文件已存在：%s\n' "$OUTPUT_KEYSTORE" >&2
    printf '如确认要覆盖，请设置 FORCE_OVERWRITE=yes 后重新运行。\n' >&2
    exit 1
fi

umask 077
output_dir="$(dirname -- "$OUTPUT_KEYSTORE")"
mkdir -p "$output_dir"
tmp_keystore="$(mktemp "$output_dir/.arkgram-release.keystore.XXXXXX")"
rm -f -- "$tmp_keystore"
cleanup() {
    rm -f -- "$tmp_keystore"
}
trap cleanup EXIT

export ARKGRAM_STORE_PASS="$KEYSTORE_PASS"
export ARKGRAM_KEY_PASS="$ALIAS_PASS"

keytool -genkeypair \
    -noprompt \
    -keystore "$tmp_keystore" \
    -storetype JKS \
    -alias "$KEY_ALIAS" \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000 \
    -storepass:env ARKGRAM_STORE_PASS \
    -keypass:env ARKGRAM_KEY_PASS \
    -dname "CN=Arkgram, OU=Arkgram, O=Arkgram, L=Unknown, ST=Unknown, C=CN"

mv -- "$tmp_keystore" "$OUTPUT_KEYSTORE"
chmod 600 "$OUTPUT_KEYSTORE"
trap - EXIT

printf '\n已生成签名库：%s\n' "$OUTPUT_KEYSTORE"
printf '密钥别名：%s\n' "$KEY_ALIAS"
printf '\n请将以下内容加入本地 local.properties，之后再转换为 GitHub Secret LOCAL_PROPERTIES：\n\n'
printf 'KEYSTORE_PASS=你刚才设置的签名库密码\n'
printf 'ALIAS_NAME=%s\n' "$KEY_ALIAS"
printf 'ALIAS_PASS=你刚才设置的密钥密码\n'
printf '\n检查签名库：\nkeytool -list -v -keystore %q\n' "$OUTPUT_KEYSTORE"
printf '\n注意：请备份这个 keystore；以后更新同一个包名必须继续使用它。\n'
