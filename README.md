# SJTU-Sports

```shell
pip install selenium pillow pytesseract
sudo apt install tesseract-ocr
```

交我办场馆预约

```shell
# 测试模式：立即运行一次，不等待 12:00
python main.py --user 'admin' --password '123456' --test

# 正式模式：默认在每日 12:00-12:10 窗口内反复遍历
python main.py --user 'admin' --password '123456' --headless
```

默认目标为：学生中心 / 学生中心健身房 / 任一天 / 15:00-16:00 / 任一可用场地。
测试模式会从最远日期往前遍历所有可预约日期一次；正式模式会在 12:00-12:10 窗口内反复执行同样的遍历，窗口外按距下次 12:00 的剩余时间动态等待。
默认不再强制使用仓库内 `chromedriver`，由 Selenium Manager 自动匹配本机 Chrome；如需固定驱动可传 `--chromedriver /path/to/chromedriver`。
