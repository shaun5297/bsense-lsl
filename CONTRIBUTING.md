# Contributing

提交改动前运行：

```bash
python -m bsense_experiment --self-test
python -m unittest discover -s tests -v
```

修改实验时序、Marker 编码或文件命名属于数据契约变更，必须：

1. 更新版本号和 `CHANGELOG.md`；
2. 更新 `config/event_codes.csv`；
3. 增加或修改测试；
4. 用短流程生成新 XDF 并验证 8 条流；
5. 不覆盖既有原始数据。

