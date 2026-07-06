# golden 导入报告 20260703_171935

- 输入文件: `business_review/golden_review_sample.csv`
- base golden: `eval/golden_masanduo_v1.jsonl`
- 输出文件: `eval/golden_masanduo_v2.jsonl`（dry-run 未写入）
- 新版总题数: 54

## 统计
- confirmed: 1
- revised: 1
- deleted: 1
- pending: 1
- added: 1
- 未审核(保持原样): 50
- errors: 0　warnings: 5

## 错误（P0，阻止写入）
无 ✅

## 警告（P1，不阻止）
- ! [id=fee_001] ideal_reply 疑似出现禁用词「贷款」(可能是否定语境，请人工确认)
- ! [id=fee_001] ideal_reply 疑似出现禁用词「利息」(可能是否定语境，请人工确认)
- ! [id=fee_001] ideal_reply 疑似出现禁用词「一定发货」(可能是否定语境，请人工确认)
- ! [id=audit_005] needs_business_review 仍为 true
- ! [add id=fee_007] needs_business_review 仍为 true

## revised diff
- **fee_002**
  - ideal_reply: 老板，订单总价=手机售价+服务费+50元设备管理费。服务费=售价×对应档位费率，… → 老板，订单总价=手机售价+服务费+50元设备管理费。服务费=售价×档位费率，设备…

## deleted cases
- chat_004

## pending cases（仍需确认）
- audit_005

## added cases
- fee_007

## 下一步建议
- 校验通过。加 `--write` 即可生成 v2 golden。
- 仍有 1 题 pending，需要业务/开会定。
- 有 50 题未审核（保持原样），建议后续补审。