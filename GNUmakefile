##############################################################################
# 
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
# 
##############################################################################

ZPHOME=$(PWD)/ZenPacks/zenoss/PythonCollector

default: egg


egg:
    # setup.py will call 'make build' before creating the egg
	python setup.py bdist_egg


build:
	@cd $(ZPHOME) && chmod a+x tests/test_watchdog.py

clean:
	rm -rf build dist
	rm -rf *.egg-info
	find . -name *.pyc | xargs -r rm
