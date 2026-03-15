# Brain Base Releases

该目录存放 `projects/base` 发布到 `/xkagent_infra/brain/base` 前后的备份与发布记录。

约定：
- 正式发布前，`scripts/publish_base.sh` 会按 root 文件和各 domain 备份目标
- 备份默认写入 `releases/publish_backups/<timestamp>/`
- 发布记录、验证结果和版本说明也可统一存放在此目录
