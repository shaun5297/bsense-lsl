# Data Directory

该目录用于本地保存实验数据，不提交 Git。

建议结构：

```text
data/
  participants/
    sub-001_ses-01_profile.json
  sub-001/
    ses-01/
      sub-001_ses-01_task-deviceqc_run-001.xdf
      logs/
```

XDF 和 JSONL 可能包含被试生理数据及实验元数据。`participants` 目录还可能包含姓名等直接身份信息，必须限制访问，并与用于训练或共享的数据分离。上传或共享前必须完成匿名化、授权和数据使用审查。
