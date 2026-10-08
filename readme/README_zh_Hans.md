# Dify CNB 数据源插件

把 CNB 仓库内容导入 Dify 知识库。

源码仓库：https://github.com/haiminovo/cnb_datasource

## 功能

- 导入仓库基础信息和 README
- 导入源码、配置和文档文件
- 导入 Issue 及其评论
- 导入 Pull Request 及其评论
- 支持 CNB SaaS 和企业版 API 地址

## 配置

### 1. 创建 CNB 访问令牌

登录 CNB，进入「个人设置 > 访问令牌」创建令牌，并勾选：

- `account-profile:r`
- `account-engage:r`
- `repo-basic-info:r`
- `repo-code:r`
- `repo-issue:r`
- `repo-pr:r`
- `repo-notes:r`

私有仓库需要额外选择对应资源范围和仓库权限。

### 2. 在 Dify 中连接

- `CNB Access Token`：上一步创建的访问令牌
- `CNB API URL`：SaaS 使用 `https://api.cnb.cool`
- `CNB URL`：SaaS 使用 `https://cnb.cool`

企业版部署可以填写实际的 API 和 Web 地址。

### 3. 选择导入范围

- `指定仓库路径`：可选，例如 `group/repository`
- `分支、标签或 Commit`：可选 CNB `ref`，留空使用默认分支
- `最多导入仓库数`：默认 20
- `导入代码文件`：默认开启
- `每个仓库代码文件数`：默认 100
- `每个仓库的 Issue 数`：默认 5
- `每个仓库的 PR 数`：默认 5

代码文件会作为独立文档出现在仓库项目下面，需要在 Dify 中勾选后才会导入。

## OAuth

插件支持 CNB OAuth 2.0。CNB OAuth 应用需要运营管理员审核，普通使用场景
建议直接配置访问令牌。

## 读取范围

- 只读，不修改 CNB 内容
- 留空时读取仓库默认分支
- 填写 branch、Tag 或 Commit SHA 时读取指定版本

## 隐私

插件只访问配置令牌有权访问的 CNB 数据，并直接发送给 CNB API 和 Dify。
详见 [PRIVACY.md](../PRIVACY.md)。

## 开发

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```
