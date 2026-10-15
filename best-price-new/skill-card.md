## Description: <br>
Shopping users can compare prices for a product across supported Chinese ecommerce platforms and receive coupon-aware purchase guidance. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[cn-shopping](https://clawhub.ai/user/cn-shopping) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
External shopping users use this skill to search product keywords, compare available JD and Taobao/Tmall results, account for coupons, and receive a recommended purchase option. The skill does not place orders, check logistics, or provide price-drop notifications. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Product search terms are sent to the publisher's Tencent Cloud proxy for JD and Taobao/Tmall searches. <br>
Mitigation: Install only when this data flow is acceptable, and avoid submitting sensitive or personal information as product queries. <br>
Risk: The release overstates Pinduoduo comparison support relative to the artifact behavior and security summary. <br>
Mitigation: Treat Pinduoduo results as unsupported until the documentation or implementation is corrected. <br>
Risk: The artifact includes a built-in proxy token for remote searches. <br>
Mitigation: Treat the token as publisher-side credential hygiene risk and prefer publisher-managed rotation or environment-provided credentials. <br>


## Reference(s): <br>
- [ClawHub skill page](https://clawhub.ai/cn-shopping/skills/best-price) <br>
- [Publisher profile](https://clawhub.ai/user/cn-shopping) <br>
- [京东自营精选](https://clawhub.ai/cn-shopping/jd-selection) <br>
- [淘宝精选](https://clawhub.ai/cn-shopping/taobao-selection) <br>
- [拼多多精选](https://clawhub.ai/cn-shopping/pdd-selection) <br>


## Skill Output: <br>
**Output Type(s):** [text, markdown, guidance] <br>
**Output Format:** [Markdown-style text with platform sections, prices, coupons, sales signals, and purchase links when available] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Requires a product keyword or title; platform selection in the artifact is limited to the supported runtime behavior.] <br>

## Skill Version(s): <br>
1.1.1 (source: server release evidence and SKILL.md frontmatter) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
