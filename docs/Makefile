OUTPUT_HTML = /tmp/README.html

default: docs

docs:
	cat top.css > $(OUTPUT_HTML)
	pandoc -sS -f markdown_mmd -t html header.md --template=template.html >> $(OUTPUT_HTML)
	pandoc -sS -f markdown -t html releases.md --template=template.html >> $(OUTPUT_HTML)
	pandoc -sS -f markdown_mmd -t html body.md \
	                       --template=template.html \
	                       --table-of-contents >> $(OUTPUT_HTML)

production: docs
	python docs.py