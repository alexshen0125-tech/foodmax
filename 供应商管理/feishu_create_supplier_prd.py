#!/usr/bin/env python3
"""
飞书云文档生成脚本 —— 供应商自助注册 PRD v1.1
===================================================
使用飞书开放平台 API 自动创建云文档并写入 PRD 全部内容。

v1.1 变更：① 移除链接过期重发功能；② 增加二级审批流程；③ 新增字段灵活配置功能。

使用前准备：
1. 在飞书开放平台 (https://open.feishu.cn) 创建应用
2. 获取 App ID 和 App Secret
3. 为应用开通权限：docx:document:create、docx:document:write
4. pip install requests

使用方式：
  python feishu_create_supplier_prd.py --app-id YOUR_APP_ID --app-secret YOUR_APP_SECRET
  # 或通过环境变量：
  export FEISHU_APP_ID=xxx
  export FEISHU_APP_SECRET=xxx
  python feishu_create_supplier_prd.py

可选参数：
  --folder-token FOLDER_TOKEN   指定飞书文件夹 token（不指定则创建在根目录）
"""

import requests
import json
import time
import argparse
import os
import sys

# ===================================================================
# 配置区 —— 在此填入你的飞书应用凭证，或通过命令行/环境变量传入
# ===================================================================
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"

# ===================================================================
# API 基础方法
# ===================================================================

def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    """获取 tenant_access_token"""
    url = f"{FEISHU_BASE_URL}/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret})
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取 token 失败: {data}")
    print(f"[OK] 获取 tenant_access_token 成功")
    return data["tenant_access_token"]


def create_document(token: str, title: str, folder_token: str = None) -> dict:
    """创建空白云文档，返回 {document_id, title}"""
    url = f"{FEISHU_BASE_URL}/docx/v1/documents"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"title": title}
    if folder_token:
        body["folder_token"] = folder_token
    resp = requests.post(url, headers=headers, json=body)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"创建文档失败: {data}")
    doc = data["data"]["document"]
    print(f"[OK] 文档已创建: {doc['title']} (ID: {doc['document_id']})")
    return doc


def create_blocks(token: str, document_id: str, block_id: str, children: list) -> list:
    """在指定 block 下批量创建子 block"""
    url = f"{FEISHU_BASE_URL}/docx/v1/documents/{document_id}/blocks/{block_id}/children"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    created = []
    batch_size = 50
    for i in range(0, len(children), batch_size):
        batch = children[i:i + batch_size]
        body = {"children": batch}
        resp = requests.post(url, headers=headers, json=body)
        data = resp.json()
        if data.get("code") != 0:
            print(f"[WARN] 批次 {i // batch_size + 1} 写入异常: code={data.get('code')}, msg={data.get('msg')}")
            for child in batch:
                single_body = {"children": [child]}
                single_resp = requests.post(url, headers=headers, json=single_body)
                single_data = single_resp.json()
                if single_data.get("code") != 0:
                    print(f"  [ERR] 写入失败: {single_data.get('msg', '')} | block_type={child.get('block_type')}")
                else:
                    created.extend(single_data.get("data", {}).get("children", []))
                time.sleep(0.3)
        else:
            created.extend(data.get("data", {}).get("children", []))
        time.sleep(0.5)

    return created


# ===================================================================
# 飞书 Block 构造工具函数
# ===================================================================

def text_element(content: str, bold: bool = False, italic: bool = False,
                 code: bool = False, color: str = None) -> dict:
    elem = {
        "text_run": {
            "content": content,
            "text_element_style": {
                "bold": bold,
                "italic": italic,
                "inline_code": code,
            }
        }
    }
    if color:
        elem["text_run"]["text_element_style"]["text_color"] = color
    return elem


def heading_block(level: int, text: str) -> dict:
    return {
        "block_type": level + 3,
        f"heading{level}": {
            "elements": [text_element(text, bold=True)]
        }
    }


def paragraph_block(elements: list) -> dict:
    return {
        "block_type": 2,
        "text": {
            "elements": elements
        }
    }


def text_para(content: str, bold: bool = False) -> dict:
    return paragraph_block([text_element(content, bold=bold)])


def divider_block() -> dict:
    return {"block_type": 22, "divider": {}}


def code_block(code_text: str, language: int = 1) -> dict:
    return {
        "block_type": 14,
        "code": {
            "elements": [text_element(code_text)],
            "language": language
        }
    }


def bullet_block(text: str, bold: bool = False) -> dict:
    return {
        "block_type": 12,
        "bullet": {
            "elements": [text_element(text, bold=bold)]
        }
    }


def ordered_block(text: str) -> dict:
    return {
        "block_type": 13,
        "ordered": {
            "elements": [text_element(text)]
        }
    }


# ===================================================================
# 表格构造
# ===================================================================

def create_table_via_api(token: str, document_id: str, parent_block_id: str,
                         headers: list, rows: list) -> str:
    """通过 API 创建表格并填充内容，返回 table block_id"""
    row_count = len(rows) + 1
    col_count = len(headers)

    table_block = {
        "block_type": 27,
        "table": {
            "property": {
                "row_size": row_count,
                "column_size": col_count,
            }
        }
    }
    result = create_blocks(token, document_id, parent_block_id, [table_block])
    if not result:
        print(f"  [ERR] 表格创建失败")
        return None

    table_id = result[0]["block_id"]

    url = f"{FEISHU_BASE_URL}/docx/v1/documents/{document_id}/blocks/{table_id}"
    resp = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })
    data = resp.json()
    if data.get("code") != 0:
        print(f"  [ERR] 获取表格结构失败: {data.get('msg')}")
        return table_id

    cells = data.get("data", {}).get("block", {}).get("table", {}).get("cells", [])

    for col_idx, header_text in enumerate(headers):
        if col_idx < len(cells[0]) if cells else False:
            cell_id = cells[0][col_idx]
            create_blocks(token, document_id, cell_id,
                         [text_para(header_text, bold=True)])
            time.sleep(0.1)

    for row_idx, row_data in enumerate(rows):
        for col_idx, cell_text in enumerate(row_data):
            actual_row = row_idx + 1
            if actual_row < len(cells) and col_idx < len(cells[actual_row]):
                cell_id = cells[actual_row][col_idx]
                create_blocks(token, document_id, cell_id,
                             [text_para(str(cell_text))])
                time.sleep(0.1)

    return table_id


# ===================================================================
# PRD 内容定义 —— 完整15章节（v1.1）
# ===================================================================

def build_prd_blocks() -> list:
    """构建 供应商自助注册 PRD v1.1 全部内容的 block 列表（非表格部分）"""
    blocks = []

    # ---- 文档元信息 ----
    blocks.append(text_para(
        "文档编号：SUP-SELF-REG-001  |  版本：v1.1  |  作者：AI Product Manager  |  "
        "创建日期：2026-04-05  |  更新日期：2026-04-05  |  状态：Draft"
    ))
    blocks.append(text_para(
        "v1.1 变更记录：① 移除链接过期重发功能（F-14 原）；"
        "② 审核流程增加采购负责人 + 财务负责人二级审批；"
        "③ 新增表单字段灵活配置功能（F-14 新）。"
    ))
    blocks.append(divider_block())

    # ---- 第一章：需求背景 ----
    blocks.append(heading_block(1, "一、需求背景 / Background"))
    blocks.append(heading_block(2, "1.1 业务痛点"))
    blocks.append(text_para("当前流程存在以下痛点："))
    blocks.append(text_para("[表格: 业务痛点]", bold=True))

    blocks.append(heading_block(2, "1.2 解决思路"))
    blocks.append(text_para(
        "将供应商注册信息采集流程线上化：采购在系统中生成唯一注册链接和二维码（自动绑定采购人信息），"
        "通过 WhatsApp / 微信发送给供应商；供应商通过手机端直接打开链接填写表单并上传资质（无需登录）；"
        "提交后采购员在中后台审核并可直接修改信息，完成后提交至采购负责人 → 财务负责人二级审批，"
        "全部通过后系统自动创建供应商档案。"
        "表单字段通过后台配置管理，支持按需增减字段、调整必填规则，无需研发上线。"
    ))

    blocks.append(heading_block(2, "1.3 核心目标"))
    blocks.append(text_para("[表格: 核心目标]", bold=True))
    blocks.append(divider_block())

    # ---- 第二章：目标用户画像 ----
    blocks.append(heading_block(1, "二、目标用户画像 / Target Users"))
    blocks.append(text_para("[表格: 用户画像]", bold=True))
    blocks.append(divider_block())

    # ---- 第三章：核心场景 ----
    blocks.append(heading_block(1, "三、核心场景 / Core Scenarios"))

    blocks.append(heading_block(2, "场景 1：采购生成邀请链接（Generate Invite）— 优先级 P0"))
    blocks.append(text_para(
        '用户故事：「作为采购员，我希望在系统中输入供应商名称和联系人后，一键生成注册链接和二维码，'
        '链接自动携带我的采购人信息（姓名、站点、币种），以便我直接通过微信或 WhatsApp 发送给供应商。」'
    ))

    blocks.append(heading_block(2, "场景 2：供应商手机端填写（Supplier Mobile Form）— 优先级 P0"))
    blocks.append(text_para(
        '用户故事：「作为供应商联系人，我希望通过微信/WhatsApp 收到的链接直接在手机浏览器中打开表单（无需注册登录），'
        '分步完成企业信息、结算信息、资质上传，支持中途保存草稿，以便我利用碎片时间完成填写。」'
    ))

    blocks.append(heading_block(2, "场景 3：采购审核 + 二级审批建档（Review & Approval）— 优先级 P0"))
    blocks.append(text_para(
        '用户故事：「作为采购员，我希望在供应商提交信息后进入审核页面，对不合规内容直接编辑修改，'
        '补充内部管理字段后提交给采购负责人审批；采购负责人通过后再流转至财务负责人审核结算信息；'
        '全部审批通过后系统自动建档，全程有操作日志留痕。」'
    ))

    blocks.append(heading_block(2, "场景 4：表单字段配置（Field Configuration）— 优先级 P1"))
    blocks.append(text_para(
        '用户故事：「作为系统管理员，我希望在字段配置中心中随时新增、隐藏或调整供应商表单的字段及必填规则，'
        '配置保存后新生成的邀请链接即时生效，以便业务快速响应字段变化，无需等待研发排期。」'
    ))
    blocks.append(divider_block())

    # ---- 第四章：业务流程 ----
    blocks.append(heading_block(1, "四、业务流程 / Business Flow"))
    blocks.append(heading_block(2, "4.1 主流程"))
    blocks.append(code_block(
        "采购员进入「注册邀请」页面\n"
        "       |\n"
        "       v\n"
        "  [ 新建邀请 ] ── 填写供应商名称、联系人、有效期\n"
        "       |\n"
        "       v\n"
        "  [ 系统生成唯一链接 + 二维码 ]\n"
        "  - 链接自动绑定：采购员、站点、币种、字段配置版本\n"
        "  - 链接含 Open Graph 标签（微信/WhatsApp 卡片预览）\n"
        "  - 二维码可下载\n"
        "       |\n"
        "  采购通过 WhatsApp / 微信 / 其他渠道发送给供应商\n"
        "       |\n"
        "       v\n"
        "  [ 供应商打开链接 ] ── 无需登录\n"
        "  - 微信内置浏览器 ✓  WhatsApp 内置浏览器 ✓  手机/PC 浏览器 ✓\n"
        "       |\n"
        "       v\n"
        "  [ 分步填写表单（字段由配置中心决定）]\n"
        "  Step 1: 企业基本信息\n"
        "  Step 2: 结算信息\n"
        "  Step 3: 资质证明 + 附件上传\n"
        "  Step 4: 确认预览并提交\n"
        "  * 每步支持「保存草稿」\n"
        "       |\n"
        "       v\n"
        "  [ 供应商提交 ] → 系统通知采购员\n"
        "       |\n"
        "       v\n"
        "  [ 采购员审核页面 ]\n"
        "  - Tab 1: 供应商填写信息（采购员可直接编辑修改，修改留痕）\n"
        "  - Tab 2: 内部补充字段（供应商不可见，采购员填写）\n"
        "  - Tab 3: 审批流程进度\n"
        "  - Tab 4: 操作日志\n"
        "       |\n"
        "       v\n"
        "  采购员点击「提交审批」\n"
        "       |\n"
        "       v\n"
        "  ┌──[ 采购负责人审批 ]\n"
        "  │   ├── 通过 ──→ [ 财务负责人审批 ]（重点：结算信息）\n"
        "  │   │               ├── 通过 ──→ 系统自动建档\n"
        "  │   │               └── 退回 → 采购员修改后重新提交（从采购负责人开始）\n"
        "  │   └── 退回 → 采购员修改后重新提交审批\n"
        "  └──────────────────────────────────────────────"
    ))

    blocks.append(heading_block(2, "4.2 邀请链接状态机"))
    blocks.append(code_block(
        "[ 已生成 ] ── 供应商打开 ──→ [ 填写中 ]\n"
        "     |                            |\n"
        "     ├── 超过有效期 → [ 已过期 ]  ├── 保存草稿 → [ 草稿 ] → 继续填写 → [ 填写中 ]\n"
        "     |                            |\n"
        "     └── 采购作废 → [ 已作废 ]    └── 提交 → [ 待采购员审核 ]\n"
        "                                                    |\n"
        "                                            采购员审核/修改/补充内部字段\n"
        "                                                    |\n"
        "                                            提交审批 → [ 待采购负责人审批 ]\n"
        "                                                    |\n"
        "                                       ├── 通过 → [ 待财务负责人审批 ]\n"
        "                                       |              ├── 通过 → [ 已通过 ] → 自动建档\n"
        "                                       |              └── 退回 → [ 审批退回 ] → 采购员修改\n"
        "                                       └── 退回 → [ 审批退回 ] → 采购员修改"
    ))

    blocks.append(heading_block(2, "4.3 审批退回处理"))
    blocks.append(text_para(
        "退回时审批人须填写退回原因（必填），系统通知采购员。"
        "采购员在审核页面修改对应字段后，可重新点击「提交审批」，审批从第一级（采购负责人）重新开始。"
    ))
    blocks.append(divider_block())

    # ---- 第五章：功能清单 ----
    blocks.append(heading_block(1, "五、功能清单 / Feature List"))
    blocks.append(heading_block(2, "5.1 功能总表"))
    blocks.append(text_para("[表格: 功能总表]", bold=True))

    blocks.append(heading_block(2, "5.2 供应商端字段清单 — 基本信息（默认配置，可通过 F-14 调整）"))
    blocks.append(text_para("[表格: 基本信息字段]", bold=True))

    blocks.append(heading_block(2, "5.3 供应商端字段清单 — 结算信息（默认配置，可通过 F-14 调整）"))
    blocks.append(text_para("[表格: 结算信息字段]", bold=True))

    blocks.append(heading_block(2, "5.4 仅采购可见的内部字段"))
    blocks.append(text_para("[表格: 内部字段]", bold=True))
    blocks.append(divider_block())

    # ---- 第六章：交互说明 ----
    blocks.append(heading_block(1, "六、交互说明 / Interaction Design"))

    blocks.append(heading_block(2, "6.1 中后台 — 新建邀请"))
    blocks.append(bullet_block("入口：供应商管理 > 注册邀请 > 「+ 新建邀请」按钮"))
    blocks.append(bullet_block("弹窗表单字段：供应商名称（必填）、联系人（必填）、联系方式、链接有效期（7/14/30天）、备注"))
    blocks.append(bullet_block("弹窗底部蓝色信息条：自动展示当前登录采购员的姓名、站点、币种"))
    blocks.append(bullet_block("提交后弹出「链接与二维码」弹窗"))

    blocks.append(heading_block(2, "6.2 中后台 — 链接与二维码弹窗"))
    blocks.append(text_para("[表格: 链接二维码弹窗]", bold=True))

    blocks.append(heading_block(2, "6.3 中后台 — 邀请列表"))
    blocks.append(text_para("[表格: 邀请列表]", bold=True))

    blocks.append(heading_block(2, "6.4 中后台 — 采购员审核页面"))
    blocks.append(text_para("四个 Tab：", bold=True))
    blocks.append(bullet_block("供应商信息：展示供应商填写的全部字段（按配置版本渲染），采购员可直接编辑修改，修改内容系统记录留痕"))
    blocks.append(bullet_block("内部补充字段：仅采购可见的管理字段，黄色标签提示「仅采购填写 · 供应商不可见」"))
    blocks.append(bullet_block("审批流程：展示当前审批进度（采购员 → 采购负责人 → 财务负责人），每步状态（待审 / 通过 / 退回+原因）均可见"))
    blocks.append(bullet_block("操作日志：时间线展示全流程操作记录"))
    blocks.append(text_para("页面底部固定操作栏：「提交审批」主按钮（首次提交及退回后重提均使用此按钮）"))

    blocks.append(heading_block(2, "6.5 中后台 — 审批人页面（采购负责人 / 财务负责人）"))
    blocks.append(text_para("[表格: 审批人页面]", bold=True))

    blocks.append(heading_block(2, "6.6 前端（H5）— 供应商填写表单"))
    blocks.append(text_para("[表格: H5表单交互]", bold=True))

    blocks.append(heading_block(2, "6.7 中后台 — 字段配置中心（F-14）"))
    blocks.append(text_para("[表格: 字段配置中心]", bold=True))

    blocks.append(heading_block(2, "6.8 前端 — 移动端适配要点"))
    blocks.append(text_para("[表格: 移动端适配]", bold=True))
    blocks.append(divider_block())

    # ---- 第七章：功能详细设计 ----
    blocks.append(heading_block(1, "七、功能详细设计 / Detailed Feature Design"))

    blocks.append(heading_block(2, "7.1 F-02 链接自动绑定采购信息"))
    blocks.append(text_para("链接结构：https://scm.foodmax.com/s/{invite_token}"))
    blocks.append(text_para("invite_token 解码后包含：", bold=True))
    blocks.append(text_para("[表格: 链接Token参数]", bold=True))
    blocks.append(text_para("供应商打开链接后，系统自动："))
    blocks.append(ordered_block("验证链接有效性（未过期、未作废）"))
    blocks.append(ordered_block("按 field_config_version 加载对应字段配置渲染表单"))
    blocks.append(ordered_block("在表单顶部展示采购对接人信息"))
    blocks.append(ordered_block("预填供应商名称（只读）和联系人（可修改）"))
    blocks.append(ordered_block("默认选中对应币种"))

    blocks.append(heading_block(2, "7.2 F-07 Open Graph 卡片预览"))
    blocks.append(code_block(
        '<meta property="og:title" content="Foodmax 供应商信息登记">\n'
        '<meta property="og:description" content="{供应商名称} — 请点击填写供应商注册信息（对接人：{采购员}）">\n'
        '<meta property="og:image" content="https://scm.foodmax.com/og-supplier.png">\n'
        '<meta property="og:type" content="website">'
    ))
    blocks.append(text_para("微信额外支持通过 wx.config + wx.updateAppMessageShareData 自定义分享卡片。"))

    blocks.append(heading_block(2, "7.3 F-08 草稿保存与恢复"))
    blocks.append(text_para("[表格: 草稿保存规则]", bold=True))

    blocks.append(heading_block(2, "7.4 F-12 二级审批流程"))
    blocks.append(text_para("审批流为顺序审批，不可并行：", bold=True))
    blocks.append(code_block(
        "采购员提交审批\n"
        "    ↓\n"
        "[采购负责人审批]\n"
        "    ├── 通过 → 系统自动通知财务负责人\n"
        "    |       ↓\n"
        "    |   [财务负责人审批]（重点：结算信息 Tab 置顶）\n"
        "    |       ├── 通过 → 触发自动建档（F-13）\n"
        "    |       └── 退回 → 通知采购员，附退回原因\n"
        "    |                  采购员修改后重新提交（从采购负责人重新开始）\n"
        "    └── 退回 → 通知采购员，附退回原因\n"
        "               采购员修改后重新提交"
    ))
    blocks.append(text_para("审批通知渠道：系统内消息 + 可选飞书/邮件通知。"))

    blocks.append(heading_block(2, "7.5 F-13 审批通过自动建档"))
    blocks.append(text_para("全部审批通过后系统自动执行：", bold=True))
    blocks.append(ordered_block("在供应商主表创建记录，生成供应商编号（旧）: S{YYYYMMDD}00001 和 供应商编号（新）: 自增序号"))
    blocks.append(ordered_block("供应商状态设为「合作」"))
    blocks.append(ordered_block("创建人 = 发起邀请的采购员，最终审批人 = 财务负责人"))
    blocks.append(ordered_block("同步至供应商列表，支持后续 查看 / 编辑 / 查看合同 / 可供仓库 操作"))
    blocks.append(ordered_block("触发通知（站内消息通知采购员建档完成；可选邮件/短信通知供应商）"))

    blocks.append(heading_block(2, "7.6 F-14 表单字段灵活配置"))
    blocks.append(text_para("字段版本管理：", bold=True))
    blocks.append(text_para("[表格: 字段版本管理]", bold=True))
    blocks.append(text_para("支持的字段类型：", bold=True))
    blocks.append(text_para("[表格: 支持字段类型]", bold=True))
    blocks.append(divider_block())

    # ---- 第八章：终端差异 ----
    blocks.append(heading_block(1, "八、终端差异说明 / Platform Differences"))
    blocks.append(text_para("[表格: 终端差异对比]", bold=True))
    blocks.append(divider_block())

    # ---- 第九章：异常处理 ----
    blocks.append(heading_block(1, "九、异常与边界处理 / Exception & Edge Cases"))
    blocks.append(text_para("[表格: 异常与边界处理]", bold=True))
    blocks.append(divider_block())

    # ---- 第十章：RBAC权限 ----
    blocks.append(heading_block(1, "十、RBAC 权限设计 / Permission Design"))
    blocks.append(heading_block(2, "10.1 角色权限矩阵"))
    blocks.append(text_para("[表格: 角色权限矩阵]", bold=True))
    blocks.append(heading_block(2, "10.2 数据隔离规则"))
    blocks.append(text_para("[表格: 数据隔离规则]", bold=True))
    blocks.append(divider_block())

    # ---- 第十一章：操作日志 ----
    blocks.append(heading_block(1, "十一、操作日志 / Audit Log"))
    blocks.append(text_para("[表格: 操作日志]", bold=True))
    blocks.append(divider_block())

    # ---- 第十二章：数据埋点 ----
    blocks.append(heading_block(1, "十二、数据埋点 / Analytics Events"))
    blocks.append(heading_block(2, "12.1 核心事件列表"))
    blocks.append(text_para("[表格: 核心事件列表]", bold=True))
    blocks.append(heading_block(2, "12.2 核心报表需求"))
    blocks.append(text_para("[表格: 核心报表需求]", bold=True))
    blocks.append(divider_block())

    # ---- 第十三章：验收标准 ----
    blocks.append(heading_block(1, "十三、验收标准 / Acceptance Criteria"))
    blocks.append(heading_block(2, "13.1 功能验收"))
    blocks.append(text_para("[表格: 功能验收]", bold=True))
    blocks.append(heading_block(2, "13.2 性能验收"))
    blocks.append(text_para("[表格: 性能验收]", bold=True))
    blocks.append(heading_block(2, "13.3 兼容性验收"))
    blocks.append(text_para("[表格: 兼容性验收]", bold=True))
    blocks.append(divider_block())

    # ---- 第十四章：缺失信息清单 ----
    blocks.append(heading_block(1, "十四、缺失信息清单 / Information Gaps"))
    blocks.append(text_para("以下信息需业务方或技术方补充确认，以便完善方案："))
    blocks.append(text_para("[表格: 缺失信息清单]", bold=True))
    blocks.append(divider_block())

    # ---- 第十五章：术语表 ----
    blocks.append(heading_block(1, "十五、术语表 / Glossary"))
    blocks.append(text_para("[表格: 术语表]", bold=True))
    blocks.append(divider_block())
    blocks.append(text_para("文档结束 / End of Document"))

    return blocks


# ===================================================================
# 表格数据定义（v1.1）—— 所有需要通过表格 API 写入的内容
# ===================================================================

ALL_TABLES = {
    "业务痛点": {
        "headers": ["痛点编号", "痛点描述", "影响范围"],
        "rows": [
            ["P-01", "采购人员需将 PDF 表格发送给供应商填写，供应商填写后再由采购人工录入系统，单次录入耗时 10-15 分钟", "所有采购员"],
            ["P-02", "供应商手写/打印 PDF 表单字迹不清、格式不统一，导致录入频繁出错（错误率约 12%）", "所有采购员"],
            ["P-03", "PDF 表格在微信/WhatsApp 中打开体验差，供应商需下载后用第三方工具填写再回传，流程断裂", "海外供应商尤为严重"],
            ["P-04", "供应商新建页面字段多（基本信息、结算信息、资质证明等 30+ 字段），供应商无法自助完成，全依赖采购代填", "全量供应商入驻场景"],
            ["P-05", "供应商提交的纸质/PDF 资质文件需采购手动上传系统，易遗漏过期证件", "合规管理"],
            ["P-06", "表单字段需求随业务变化频繁，修改字段需要研发介入，迭代周期长", "产品/运营团队"],
        ]
    },
    "核心目标": {
        "headers": ["指标", "当前值", "目标值", "衡量方式"],
        "rows": [
            ["单个供应商入驻耗时", "25-40 min（PDF 流转 + 手工录入）", "≤ 10 min（采购审核 + 审批）", "从发起邀请到供应商建档的平均时长"],
            ["供应商信息录入错误率", "~12%", "≤ 2%", "建档后信息修改次数 / 总建档数"],
            ["采购手工录入工作量", "100%（全部字段人工填写）", "≤ 15%（仅补充内部管理字段）", "采购填写字段数 / 总字段数"],
            ["供应商填写完成率", "~65%（PDF 流程中断率高）", "≥ 90%", "提交数 / 邀请数"],
            ["字段变更上线周期", "1-2 周（研发排期）", "≤ 1 天（配置中心操作）", "需求提出到字段生效时长"],
        ]
    },
    "用户画像": {
        "headers": ["角色", "典型画像", "核心诉求", "使用频率"],
        "rows": [
            ["采购员", "负责供应商开发与维护，需频繁录入供应商信息", "减少手工录入，一键生成链接发给供应商自助填写", "每周 3-10 次"],
            ["采购负责人", "采购团队管理者，对供应商入驻质量和合规性负责", "快速审批采购员提交的供应商信息，确保信息准确合规", "每周 5-20 次"],
            ["财务负责人", "财务团队管理者，对结算信息和付款条件负责", "核验银行账户、结算方式等财务字段，防范付款风险", "每周 5-15 次"],
            ["供应商联系人", "企业行政/财务人员，通过微信/WhatsApp 收到注册链接", "手机端快速填写，不想下载 App，填写过程不丢失", "一次性"],
            ["系统管理员", "负责系统配置与维护", "灵活管理表单字段，快速响应业务字段变更需求", "按需"],
        ]
    },
    "功能总表": {
        "headers": ["功能编号", "功能名称", "优先级", "所属端", "说明"],
        "rows": [
            ["F-01", "新建注册邀请", "P0", "中后台", "采购填写供应商名称、联系人、有效期，生成链接和二维码"],
            ["F-02", "链接自动绑定采购信息", "P0", "中后台", "链接携带采购员、站点、币种、字段配置版本，供应商端自动显示"],
            ["F-03", "二维码生成与下载", "P0", "中后台", "生成含 Foodmax Logo 的二维码，支持 PNG 下载"],
            ["F-04", "邀请列表管理", "P0", "中后台", "查看全部邀请记录，筛选状态，复制链接/查看二维码"],
            ["F-05", "供应商端分步表单", "P0", "前端（H5）", "4 步填写：基本信息→结算信息→资质附件→确认提交"],
            ["F-06", "移动端适配", "P0", "前端（H5）", "适配微信/WhatsApp 内置浏览器，响应式布局"],
            ["F-07", "Open Graph 卡片预览", "P0", "前端（H5）", "链接在微信/WhatsApp 中展示富媒体卡片（标题+描述+图标）"],
            ["F-08", "草稿保存与恢复", "P0", "前端（H5）", "供应商中途关闭后重新打开链接可恢复填写进度"],
            ["F-09", "资质文件上传", "P0", "前端（H5）", "支持拍照/相册上传，PDF/JPG/PNG，大小上限可配置"],
            ["F-10", "信息审核页面（采购员）", "P0", "中后台", "展示供应商提交的全部信息，采购员可直接编辑修改后提交审批"],
            ["F-11", "内部字段补充", "P0", "中后台", "供应商等级、合同扣点、是否参与结算等仅采购可见字段"],
            ["F-12", "二级审批流程", "P0", "中后台", "采购负责人 → 财务负责人顺序审批，支持通过/退回+原因"],
            ["F-13", "审批通过自动建档", "P0", "中后台", "全部审批通过后自动创建供应商记录，生成编号，同步至供应商列表"],
            ["F-14", "表单字段灵活配置", "P1", "中后台（配置中心）", "管理员可增删字段、调整必填规则、设置显示分组，无需研发上线"],
            ["F-15", "操作日志", "P0", "中后台", "记录全流程操作：邀请创建、供应商提交、审核修改、审批通过/退回"],
            ["F-16", "批量邀请", "P2", "中后台", "Excel 导入批量生成邀请链接"],
        ]
    },
    "基本信息字段": {
        "headers": ["字段名", "字段类型", "默认必填", "供应商可填", "说明"],
        "rows": [
            ["供应商名称", "文本（只读）", "是", "否（采购预填）", "邀请时由采购填入，供应商端只读展示"],
            ["供应商名称（英文）", "文本", "否", "是", "供应商填写"],
            ["供应商简称", "文本", "否", "是", "供应商填写"],
            ["供应商地址", "文本", "是", "是", "—"],
            ["联系人", "文本", "是", "是", "邀请时预填，供应商可修改"],
            ["联系方式", "选择+文本", "是", "是", "手机/座机 + 号码"],
            ["供应商单位类型", "下拉选择", "是", "是", "有限责任公司/股份有限公司/个体工商户/合伙企业"],
            ["纳税人类型", "下拉选择", "是", "是", "一般纳税人/小规模纳税人"],
            ["唯一码识别号类型", "下拉选择", "是", "是", "统一社会信用代码/组织机构代码/营业执照注册号"],
            ["纳税人识别号", "文本", "是", "是", "统一社会信用代码"],
            ["是否农业生产者", "单选", "是", "是", "否/是"],
            ["定价方式", "下拉选择", "是", "是", "含税/不含税"],
        ]
    },
    "结算信息字段": {
        "headers": ["字段名", "字段类型", "默认必填", "供应商可填", "说明"],
        "rows": [
            ["付款类型", "单选", "是", "是", "后付费/预付费"],
            ["结算方式", "下拉选择", "是", "是", "月结/半月结/周结"],
            ["结算币种", "下拉选择", "是", "是", "默认从链接继承（SGD/CNY/USD 等）"],
            ["财务联系人", "文本", "否", "是", "—"],
            ["财务联系方式", "文本", "否", "是", "—"],
            ["账户名称", "文本", "是", "是", "开户名"],
            ["账户名称（英文）", "文本", "否", "是", "—"],
            ["SWIFT 代码", "文本", "否", "是", "国际汇款用"],
            ["所属国家", "下拉选择", "否", "是", "—"],
            ["银行收款号", "文本", "是", "是", "银行账号"],
            ["银行大类", "下拉选择", "是", "是", "OCBC/DBS/UOB 等"],
            ["银行支行", "文本", "否", "是", "—"],
        ]
    },
    "内部字段": {
        "headers": ["字段名", "字段类型", "是否必填", "说明"],
        "rows": [
            ["供应商属性", "下拉选择", "是", "常规供应商/战略供应商/临时供应商"],
            ["供应商等级", "下拉选择", "是", "A级/B级/C级"],
            ["供应商性质", "下拉选择", "是", "生产商/贸易商/代理商"],
            ["是否参与结算", "下拉选择", "是", "是/否"],
            ["合同扣点", "数值", "否", "百分比"],
            ["最晚付款日（票到后）", "下拉选择", "是", "30天/45天/60天/90天"],
            ["合同有效期", "日期范围", "否", "起止日期"],
            ["供应商状态", "系统自动", "是", "默认「草稿」，全部审批通过后变为「合作」"],
            ["是否测试供应商", "单选", "是", "默认「否」"],
        ]
    },
    "链接二维码弹窗": {
        "headers": ["交互元素", "说明"],
        "rows": [
            ["采购信息绑定提示", "蓝色信息条，展示链接已绑定的采购员、站点、币种"],
            ["短链接展示", "格式 scm.foodmax.com/s/XXXXX，带「复制链接」按钮"],
            ["二维码", "含 Foodmax Logo 的二维码，带「下载二维码」按钮"],
            ["卡片预览", "展示微信/WhatsApp 中链接打开时的 OG 卡片效果"],
            ["使用提示", "黄色提示条：复制链接通过微信/WhatsApp 发送，或下载二维码让供应商扫码"],
            ["有效期与通知说明", "灰色文字：有效期、无需登录、提交后通知采购员"],
        ]
    },
    "邀请列表": {
        "headers": ["列", "说明"],
        "rows": [
            ["邀请编号", "系统自动生成 INV-YYYYMMDD-NNN"],
            ["供应商名称", "邀请时填写"],
            ["联系人", "邀请时填写"],
            ["发起人", "当前登录采购员"],
            ["发起时间", "—"],
            ["有效期", "到期日"],
            ["状态", "待填写 / 待采购员审核（红点）/ 待采购负责人审批 / 待财务审批 / 审批退回（红点）/ 已通过 / 已过期 / 已作废"],
            ["操作", "待审核→「去审核」/ 审批退回→「去修改」/ 待填写→「复制链接」「二维码」/ 已通过→「查看详情」/ 审批人→「去审批」"],
        ]
    },
    "审批人页面": {
        "headers": ["交互元素", "说明"],
        "rows": [
            ["待审任务入口", "系统通知 + 邀请列表「去审批」按钮"],
            ["信息展示", "只读展示供应商全部信息 + 采购员修改记录高亮（diff 标注）"],
            ["财务负责人专属视图", "结算信息 Tab 置顶，其余字段收起"],
            ["审批操作", "「通过」绿色按钮 / 「退回」红色按钮（退回需填写原因，必填）"],
            ["退回原因", "文本输入框，提交后显示在操作日志和采购员的退回提醒中"],
        ]
    },
    "H5表单交互": {
        "headers": ["交互元素", "说明"],
        "rows": [
            ["顶部 Header", "绿色渐变背景，展示「供应商信息登记」标题 + 采购对接人信息条"],
            ["步骤条", "Sticky 置顶，4 步圆点指示器：基本信息→结算信息→资质附件→确认提交"],
            ["表单卡片", "白色圆角卡片分组展示字段（字段列表由配置中心决定），必填字段标红星"],
            ["输入控件", "最小触控区域 44×44px，输入框高度 44px，圆角 8px"],
            ["操作按钮", "底部固定，主按钮「下一步」+ 次按钮「保存草稿」+ 返回「上一步」"],
            ["资质上传", "点击上传或调用手机相机拍照，实时预览已上传文件"],
            ["确认页", "分区域汇总全部已填信息，底部绿色「确认提交」按钮"],
            ["成功页", "提交成功图标 + 提交摘要（供应商名称、时间、对接人、邀请编号）"],
            ["过期页", "链接过期图标 + 提示联系采购人员获取新链接"],
        ]
    },
    "字段配置中心": {
        "headers": ["交互元素", "说明"],
        "rows": [
            ["入口", "系统设置 > 供应商表单 > 字段配置"],
            ["字段列表", "按分组（基本信息 / 结算信息 / 资质附件）展示所有字段，支持拖拽排序"],
            ["字段操作", "启用/禁用字段（禁用后不在供应商表单展示）、切换必填/选填"],
            ["新增字段", "支持字段类型：文本、数值、单选、多选（下拉）、日期、文件上传；需填写字段标签（中/英文）"],
            ["选项管理", "下拉/单选字段支持在线维护选项列表"],
            ["配置生效规则", "配置保存后，新生成的邀请链接使用新配置；已生成链接保持旧版本字段，避免供应商填写中断"],
            ["预览", "配置保存前支持「预览 H5 效果」，模拟供应商视角查看表单"],
        ]
    },
    "移动端适配": {
        "headers": ["适配项", "规格"],
        "rows": [
            ["viewport", "width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"],
            ["布局", "单列布局，字段全宽"],
            ["输入框", "高度 ≥ 44px，字号 ≥ 14px（避免 iOS 缩放）"],
            ["步骤条", "Sticky 置顶，窄屏幕隐藏文字仅保留圆点"],
            ["上传", "调用系统相机/相册选择器"],
            ["草稿存储", "服务端存储，cookie/token 关联链接 ID"],
            ["WhatsApp 兼容", "标准 HTML5，无特殊 API 依赖"],
            ["微信兼容", "支持微信 JS-SDK 分享接口（可选），标准 H5 页面兼容微信内置浏览器"],
            ["Open Graph", "og:title / og:description / og:image 标签，实现分享卡片预览"],
        ]
    },
    "链接Token参数": {
        "headers": ["参数", "说明"],
        "rows": [
            ["invite_id", "邀请记录 ID"],
            ["buyer_id", "采购员 ID"],
            ["buyer_name", "采购员姓名"],
            ["site_code", "站点编码（如 SG_XIAOMAN）"],
            ["currency", "币种（如 SGD）"],
            ["supplier_name", "供应商名称（预填至表单）"],
            ["contact_name", "联系人（预填至表单）"],
            ["field_config_version", "字段配置版本号（决定渲染哪套字段）"],
            ["expire_at", "过期时间戳"],
        ]
    },
    "草稿保存规则": {
        "headers": ["场景", "处理"],
        "rows": [
            ["点击「保存草稿」", "表单数据序列化后存储至服务端，关联 invite_id"],
            ["浏览器意外关闭", "下次打开同一链接自动恢复草稿，提示「检测到上次未提交的草稿，是否恢复？」"],
            ["填写超过 30 分钟未操作", "自动保存当前进度"],
            ["链接过期前已保存草稿", "仍允许继续填写并提交（宽限期 24h）"],
            ["供应商已提交", "再次打开链接展示「已提交」状态页"],
        ]
    },
    "字段版本管理": {
        "headers": ["概念", "说明"],
        "rows": [
            ["字段配置版本", "每次保存配置生成新版本号（v1, v2...），已有邀请链接锁定其生成时的版本"],
            ["版本锁定", "供应商端按 invite_token 中的 field_config_version 渲染，不受后续配置变更影响"],
            ["向前兼容", "旧版本配置永久保留，确保旧链接可正常打开和提交"],
        ]
    },
    "支持字段类型": {
        "headers": ["类型", "说明", "示例"],
        "rows": [
            ["文本（单行）", "短文本输入", "供应商名称、联系人"],
            ["文本（多行）", "长文本输入", "备注、地址"],
            ["数值", "数字输入，支持小数位设置", "合同扣点"],
            ["单选", "选项互斥，支持自定义选项", "付款类型、纳税人类型"],
            ["下拉多选", "下拉选择，支持自定义选项", "结算方式"],
            ["日期", "日期选择器", "合同有效期"],
            ["文件上传", "支持 PDF/JPG/PNG，大小上限可配置（1-50MB）", "营业执照、资质证书"],
        ]
    },
    "终端差异对比": {
        "headers": ["特性", "中后台（Web）", "供应商端（H5）"],
        "rows": [
            ["访问方式", "PC 浏览器登录 SCM 系统", "微信/WhatsApp/手机浏览器打开链接"],
            ["身份认证", "系统账号登录", "无需登录，链接即凭证"],
            ["布局", "左侧导航 + 内容区，双列表单", "单列全宽表单，卡片式分组"],
            ["字段渲染", "按当前最新配置展示（审核页）", "按链接携带的字段版本号渲染（冻结版本）"],
            ["表单交互", "鼠标操作，下拉选择", "触控操作，原生选择器"],
            ["文件上传", "拖拽 + 点击选择", "拍照 / 相册 / 文件管理器"],
            ["资质预览", "弹窗预览 PDF/图片", "内联预览 + 点击全屏"],
            ["操作按钮", "页面顶部右侧固定", "页面底部全宽固定"],
        ]
    },
    "异常与边界处理": {
        "headers": ["编号", "异常场景", "处理策略", "用户提示"],
        "rows": [
            ["E-01", "链接已过期", "展示过期页面，显示采购对接人信息", "此链接已过期，请联系采购人员 {姓名} 获取新链接"],
            ["E-02", "链接已作废", "同 E-01", "此链接已失效"],
            ["E-03", "供应商重复提交", "展示已提交状态页", "您的信息已提交，正在审核中"],
            ["E-04", "上传文件超过限制大小", "阻止上传", "文件大小超出限制（最大 {配置值}MB），请压缩后重新上传"],
            ["E-05", "上传非支持格式", "阻止上传", "请上传 PDF、JPG 或 PNG 格式的文件"],
            ["E-06", "网络中断（供应商端）", "自动保存草稿，恢复后提示", "网络异常，已自动保存草稿"],
            ["E-07", "必填字段未填", "阻止进入下一步，高亮未填字段", "请填写标红的必填项"],
            ["E-08", "纳税人识别号格式校验失败", "提交时校验", "请输入正确的统一社会信用代码（18位）"],
            ["E-09", "银行账号格式异常", "提交时校验，不阻断", "请确认银行账号是否正确"],
            ["E-10", "同名供应商已存在", "审核时系统提示采购", "系统中已存在同名供应商 {编号}，请确认是否重复"],
            ["E-11", "资质证件过期", "允许上传但标黄警告", "该证件已过有效期，请确认"],
            ["E-12", "审批退回后供应商信息未变更", "允许重新提交，日志标注「无修改重新提交」", "—"],
            ["E-13", "字段配置变更后旧链接访问", "按 field_config_version 渲染旧版本字段，不影响填写", "—"],
            ["E-14", "采购审核时供应商同时在修改草稿", "以供应商最新提交为准", "供应商已更新信息，请刷新页面查看最新版本"],
        ]
    },
    "角色权限矩阵": {
        "headers": ["功能模块", "操作", "采购员", "采购负责人", "财务负责人", "系统管理员"],
        "rows": [
            ["注册邀请", "新建邀请", "✅", "✅", "❌", "❌"],
            ["注册邀请", "查看邀请列表", "✅仅自己", "✅全部", "✅全部", "✅全部"],
            ["注册邀请", "作废邀请", "✅仅自己", "✅全部", "❌", "❌"],
            ["审核", "查看/编辑供应商信息", "✅仅自己发起的", "✅全部（只读）", "✅全部（只读）", "❌"],
            ["审核", "提交审批", "✅", "❌", "❌", "❌"],
            ["审批", "采购负责人审批（通过/退回）", "❌", "✅", "❌", "❌"],
            ["审批", "财务负责人审批（通过/退回）", "❌", "❌", "✅", "❌"],
            ["供应商列表", "查看", "✅", "✅", "✅", "✅"],
            ["供应商列表", "编辑", "✅", "✅", "✅", "✅"],
            ["字段配置", "查看/编辑字段配置", "❌", "❌", "❌", "✅"],
        ]
    },
    "数据隔离规则": {
        "headers": ["维度", "隔离规则"],
        "rows": [
            ["组织架构", "采购员只能查看自己发起的邀请记录"],
            ["站点", "链接自动绑定发起人所属站点"],
            ["审核范围", "采购员仅审核自己发起的邀请；采购负责人和财务负责人可查看全部"],
            ["审批顺序", "财务负责人的审批入口仅在采购负责人通过后才激活"],
        ]
    },
    "操作日志": {
        "headers": ["操作", "记录字段", "说明"],
        "rows": [
            ["创建邀请", "操作人、时间、供应商名称、联系人、有效期、字段配置版本", "—"],
            ["生成链接/二维码", "链接URL、二维码hash", "—"],
            ["供应商打开链接", "IP、User-Agent、时间", "用于判断填写渠道（微信/WhatsApp/浏览器）"],
            ["供应商保存草稿", "草稿版本号、已填字段数", "—"],
            ["供应商提交", "提交时间、全部表单数据快照", "JSON 格式"],
            ["采购员修改字段", "修改人、字段名、修改前值、修改后值", "逐字段记录"],
            ["采购员提交审批", "提交人、时间", "—"],
            ["采购负责人审批通过", "审批人、时间", "—"],
            ["采购负责人退回", "审批人、时间、退回原因", "—"],
            ["财务负责人审批通过", "审批人、时间", "—"],
            ["财务负责人退回", "审批人、时间、退回原因", "—"],
            ["建档完成", "操作人（系统）、时间、生成的供应商编号", "—"],
            ["字段配置变更", "操作人、时间、变更内容（字段名/变更类型）", "字段配置独立日志"],
        ]
    },
    "核心事件列表": {
        "headers": ["事件名", "触发时机", "携带参数"],
        "rows": [
            ["invite_create", "采购新建邀请", "buyer_id, supplier_name, expire_days, field_config_version"],
            ["invite_link_copy", "复制链接", "buyer_id, invite_id"],
            ["invite_qr_download", "下载二维码", "buyer_id, invite_id"],
            ["form_open", "供应商打开链接", "invite_id, source(wechat/whatsapp/browser), device_type"],
            ["form_step_complete", "供应商完成某一步", "invite_id, step_number, duration_ms"],
            ["form_draft_save", "供应商保存草稿", "invite_id, step_number, filled_fields_count"],
            ["form_submit", "供应商提交", "invite_id, total_duration_ms, device_type"],
            ["form_expired_view", "供应商看到过期页", "invite_id"],
            ["review_open", "采购员打开审核页", "buyer_id, invite_id"],
            ["review_field_edit", "采购员修改供应商字段", "buyer_id, field_name"],
            ["review_submit_approval", "采购员提交审批", "buyer_id, invite_id"],
            ["approval_action", "审批人操作（通过/退回）", "approver_id, approver_role, action(approve/reject), invite_id"],
            ["archive_complete", "系统完成建档", "invite_id, supplier_id, total_duration_from_invite_ms"],
            ["field_config_change", "管理员变更字段配置", "admin_id, field_name, change_type(add/disable/required_toggle)"],
        ]
    },
    "核心报表需求": {
        "headers": ["报表名称", "统计口径", "刷新频率", "筛选维度"],
        "rows": [
            ["邀请转化漏斗", "已发起 → 已打开 → 已填写 → 已提交 → 审批中 → 已通过", "每日T+1", "日期、采购员、站点"],
            ["审批耗时分析", "采购员提交审批到建档完成的平均时长（分采购负责人/财务分段）", "每日T+1", "日期、审批人"],
            ["填写渠道占比", "微信/WhatsApp/浏览器 分布", "每周", "日期、站点"],
            ["审批退回率", "退回次数 / 总审批次数", "每周", "日期、退回原因分类"],
            ["采购字段修改率", "审核中修改的字段数 / 总字段数", "每周", "采购员、字段类型"],
        ]
    },
    "功能验收": {
        "headers": ["编号", "验收项", "验收标准", "优先级"],
        "rows": [
            ["AC-01", "生成链接", "链接可在微信/WhatsApp/Chrome/Safari 中正常打开", "P0"],
            ["AC-02", "二维码", "微信扫码、WhatsApp 扫码均可正常打开表单", "P0"],
            ["AC-03", "采购信息绑定", "供应商端正确展示采购员、站点、币种", "P0"],
            ["AC-04", "分步表单", "4 步流转正常，必填校验生效", "P0"],
            ["AC-05", "移动端适配", "iPhone SE ~ iPhone 15 Pro Max、主流安卓机型正常展示", "P0"],
            ["AC-06", "微信内置浏览器", "表单填写、文件上传、提交全流程正常", "P0"],
            ["AC-07", "WhatsApp 内置浏览器", "表单填写、文件上传、提交全流程正常", "P0"],
            ["AC-08", "草稿保存", "关闭页面后重新打开可恢复填写进度", "P0"],
            ["AC-09", "资质上传", "手机拍照、相册选择、PDF 上传均正常", "P0"],
            ["AC-10", "采购员审核修改", "采购员可编辑全部供应商字段，修改有日志记录", "P0"],
            ["AC-11", "采购负责人审批", "通过/退回+原因均正常，退回后采购员收到通知", "P0"],
            ["AC-12", "财务负责人审批", "通过/退回+原因均正常，仅采购负责人通过后可操作", "P0"],
            ["AC-13", "自动建档", "财务通过后供应商列表新增记录，编号正确", "P0"],
            ["AC-14", "字段配置新增字段", "新字段在新生成的邀请链接 H5 表单中正确渲染", "P1"],
            ["AC-15", "字段配置版本隔离", "配置变更后旧链接仍按旧版本字段渲染，不受影响", "P1"],
            ["AC-16", "字段禁用", "禁用字段后新表单不展示该字段，已提交数据中字段保留", "P1"],
        ]
    },
    "性能验收": {
        "headers": ["编号", "验收项", "验收标准"],
        "rows": [
            ["PC-01", "表单页面加载（4G 网络）", "≤ 3s"],
            ["PC-02", "草稿保存响应", "≤ 1s"],
            ["PC-03", "表单提交响应", "≤ 2s"],
            ["PC-04", "文件上传（5MB）", "≤ 10s"],
            ["PC-05", "二维码生成", "≤ 1s"],
            ["PC-06", "审核/审批页面加载", "≤ 2s"],
            ["PC-07", "自动建档", "≤ 3s"],
        ]
    },
    "兼容性验收": {
        "headers": ["编号", "验收项", "验收标准"],
        "rows": [
            ["CC-01", "微信内置浏览器", "iOS 微信 8.0+, Android 微信 8.0+"],
            ["CC-02", "WhatsApp 内置浏览器", "iOS WhatsApp 2.23+, Android WhatsApp 2.23+"],
            ["CC-03", "手机浏览器", "Safari 15+, Chrome 90+"],
            ["CC-04", "PC 浏览器（中后台）", "Chrome 90+, Edge 90+"],
            ["CC-05", "Open Graph 预览", "微信和 WhatsApp 中正确展示卡片标题、描述、图标"],
            ["CC-06", "与现有供应商模块兼容", "建档数据与手工新建数据结构一致"],
        ]
    },
    "缺失信息清单": {
        "headers": ["编号", "缺失信息", "影响模块", "需确认方"],
        "rows": [
            ["G-01", "短链接服务是否已有？还是需要新建？", "链接生成", "后端/运维团队"],
            ["G-02", "微信 JS-SDK 的 AppID 和域名白名单配置", "微信分享卡片", "前端+运维"],
            ["G-03", "供应商端表单域名（是否复用 scm.foodmax.com 或独立域名）", "前端部署", "后端/运维团队"],
            ["G-04", "现有供应商新建接口能否复用？还是需新建", "自动建档", "后端团队"],
            ["G-05", "资质文件存储方案（OSS/S3 还是现有文件服务）", "文件上传", "后端团队"],
            ["G-06", "草稿数据存储方案（Redis 还是 DB）", "草稿保存", "后端团队"],
            ["G-07", "系统通知渠道（站内消息/邮件/飞书通知）", "审核通知、审批通知", "产品+后端"],
            ["G-08", "银行列表主数据来源和下拉选项维护方", "结算信息", "主数据团队"],
            ["G-09", "供应商编号（旧/新）的生成规则确认", "自动建档", "后端团队"],
            ["G-10", "多语言需求（中文/英文/其他语言表单）", "国际化", "产品团队"],
            ["G-11", "采购负责人和财务负责人角色是否已在系统中存在？如需新建，对应哪个部门/岗位？", "RBAC、审批流", "HR/系统管理员"],
            ["G-12", "审批退回后是否支持「仅重走退回节点」还是必须从头开始审批？", "审批流", "产品+业务方"],
            ["G-13", "字段配置中心的操作权限是否需要细化（例如财务负责人可配置结算类字段）？", "字段配置 RBAC", "产品+业务方"],
        ]
    },
    "术语表": {
        "headers": ["术语", "英文", "说明"],
        "rows": [
            ["注册邀请", "Registration Invite", "采购在系统中创建的供应商注册请求，包含唯一链接"],
            ["H5 表单", "H5 Form", "基于 HTML5 的移动端网页表单，无需安装 App"],
            ["Open Graph", "Open Graph Protocol", "Facebook 推出的网页元数据协议，被微信/WhatsApp 采用实现链接卡片预览"],
            ["内置浏览器", "In-App Browser", "微信/WhatsApp 内部嵌入的网页浏览器，无需跳转外部浏览器"],
            ["草稿", "Draft", "供应商保存但未提交的表单数据"],
            ["建档", "Archiving", "全部审批通过后在供应商主数据中创建正式记录"],
            ["OG 卡片", "OG Card", "链接在社交应用中展示的富媒体预览卡片（标题+描述+图片）"],
            ["RBAC", "Role-Based Access Control", "基于角色的访问控制"],
            ["字段配置版本", "Field Config Version", "字段配置每次保存生成的版本快照，用于确保旧链接字段不受新配置影响"],
            ["二级审批", "Two-level Approval", "采购负责人 → 财务负责人的顺序审批流程"],
        ]
    },
}


# ===================================================================
# 主执行逻辑
# ===================================================================

def main():
    parser = argparse.ArgumentParser(description="创建飞书云文档 - 供应商自助注册 PRD v1.1")
    parser.add_argument("--app-id", default=FEISHU_APP_ID, help="飞书应用 App ID")
    parser.add_argument("--app-secret", default=FEISHU_APP_SECRET, help="飞书应用 App Secret")
    parser.add_argument("--folder-token", default=None, help="飞书文件夹 token（可选）")
    parser.add_argument("--dry-run", action="store_true", help="仅输出 block 数量，不调用 API")
    args = parser.parse_args()

    blocks = build_prd_blocks()
    print(f"\n📄 PRD 内容构建完成: {len(blocks)} 个 blocks, {len(ALL_TABLES)} 个表格")

    if args.dry_run:
        print("\n[DRY RUN] 以下为将要创建的内容结构：")
        for i, b in enumerate(blocks):
            bt = b.get("block_type", "?")
            type_map = {2: "段落", 4: "H1", 5: "H2", 6: "H3", 7: "H4", 12: "列表", 13: "有序列表", 14: "代码", 22: "分割线", 27: "表格"}
            label = type_map.get(bt, f"type={bt}")
            preview = ""
            for key in ["text", "heading1", "heading2", "heading3", "heading4", "bullet", "ordered", "code"]:
                if key in b.get(key, b):
                    content = b.get(key, {})
                    if isinstance(content, dict):
                        elems = content.get("elements", [])
                        if elems:
                            preview = elems[0].get("text_run", {}).get("content", "")[:50]
                    break
            print(f"  [{i+1:3d}] {label:8s} | {preview}")

        print(f"\n  表格列表:")
        for name, data in ALL_TABLES.items():
            print(f"    - {name}: {len(data['headers'])}列 × {len(data['rows'])}行")
        print(f"\n共计 {len(blocks)} blocks + {len(ALL_TABLES)} tables")
        return

    if not args.app_id or not args.app_secret:
        print("\n❌ 错误：缺少飞书应用凭证")
        print("请通过以下方式之一提供：")
        print("  1. 命令行参数: python feishu_create_supplier_prd.py --app-id YOUR_ID --app-secret YOUR_SECRET")
        print("  2. 环境变量:   export FEISHU_APP_ID=xxx && export FEISHU_APP_SECRET=xxx")
        sys.exit(1)

    # 1. 获取 token
    token = get_tenant_access_token(args.app_id, args.app_secret)

    # 2. 创建文档
    doc = create_document(token, "供应商自助注册 产品需求文档（PRD）v1.1", args.folder_token)
    doc_id = doc["document_id"]

    # 3. 写入主体 blocks
    print(f"\n📝 开始写入文档内容 ({len(blocks)} blocks)...")
    created = create_blocks(token, doc_id, doc_id, blocks)
    print(f"[OK] 主体内容写入完成，共 {len(created)} blocks")

    # 4. 查找占位文本，替换为表格
    print(f"\n📊 开始创建表格 ({len(ALL_TABLES)} 个)...")

    url = f"{FEISHU_BASE_URL}/docx/v1/documents/{doc_id}/blocks"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params={"page_size": 500})
    all_blocks = resp.json().get("data", {}).get("items", [])

    table_count = 0
    for block in all_blocks:
        if block.get("block_type") != 2:
            continue
        text_content = ""
        text_block = block.get("text", {})
        for elem in text_block.get("elements", []):
            tr = elem.get("text_run", {})
            text_content += tr.get("content", "")

        if text_content.startswith("[表格:") and text_content.endswith("]"):
            table_name = text_content[4:-1].strip()
            if table_name in ALL_TABLES:
                table_data = ALL_TABLES[table_name]
                parent_id = block.get("parent_id", doc_id)
                print(f"  创建表格: {table_name} ({len(table_data['headers'])}×{len(table_data['rows'])+1})")
                create_table_via_api(token, doc_id, parent_id, table_data["headers"], table_data["rows"])
                table_count += 1
                time.sleep(0.5)

    print(f"[OK] 表格创建完成，共 {table_count} 个")

    # 5. 输出结果
    doc_url = f"https://bytedance.feishu.cn/docx/{doc_id}"
    print(f"\n{'='*60}")
    print(f"✅ 飞书云文档创建成功！")
    print(f"📎 文档链接: {doc_url}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
