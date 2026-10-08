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

### 仓库路径怎么填

从浏览器中的 CNB 仓库地址复制路径，例如：

```text
https://cnb.cool/organization/group/repository
```

仓库路径填写：

```text
organization/group/repository
```

以下格式都支持：

```text
organization/group/repository
https://cnb.cool/organization/group/repository
https://cnb.cool/organization/group/repository.git
https://cnb.cool/organization/group/repository/-/blob/main/README.md
```

多个仓库可以使用逗号或换行分隔：

```text
organization/group/repository-a
organization/group/repository-b
organization/other/repository
```

不要只填 `repository`，必须包含完整的组织、子组织和仓库路径。留空时会
扫描当前令牌有权限访问的所有仓库。

如果仓库路径留空但填写了分支，插件会把这个分支应用到所有有权限的仓库。
某些仓库没有该分支或不能读取代码时，会显示为 `(ref unavailable)`，并跳过
该仓库的 README 和代码，不会导致整个数据源失败。

### 引用类型和引用值怎么填

`引用类型` 和 `分支、标签或 Commit` 要配合使用：

| 引用类型 | 引用值示例 | 解析方式 |
| :- | :- | :- |
| 自动 | `develop` | 直接传给 CNB，由 CNB 自行解析 |
| 分支 | `develop` | 调用 CNB 分支接口并解析为 Commit SHA |
| 标签 | `v1.0.0` | 调用 CNB 标签接口并解析为 Commit SHA |
| Commit | `a1b2c3d4...` | 直接使用指定 Commit SHA |

插件会在读取文件前把分支和标签解析成 Commit SHA。因此即使分支和标签同名，
只要选择正确的“引用类型”，就不会产生歧义。

“自动”模式只用于兼容旧版本。如果分支名包含斜杠，例如 `feature/login`，
请选择“分支”并直接填写完整分支名。

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
