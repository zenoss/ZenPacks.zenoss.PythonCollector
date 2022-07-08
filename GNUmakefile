##############################################################################
#
# Copyright (C) Zenoss, Inc. 2019, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

ZP_DIR=$(PWD)/ZenPacks/zenoss/PythonCollector
SRC_DIR=$(PWD)/src
LIB_DIR=$(ZP_DIR)/lib
BUILD_DIR=$(ZP_DIR)/build

MONOTONIC_SRC=$(SRC_DIR)/monotonic-1.5.tar.gz
MONOTONIC_DIR=$(LIB_DIR)/monotonic

default: egg

egg:
	# setup.py will call 'make build' before creating the egg
	python setup.py bdist_egg

$(MONOTONIC_DIR):
	mkdir -p $(MONOTONIC_DIR)

py_monotonic: $(MONOTONIC_SRC) $(MONOTONIC_DIR)
	rm -rf $(BUILD_DIR); mkdir -p $(BUILD_DIR)
	cd $(BUILD_DIR); tar zxf $(MONOTONIC_SRC) --strip-components=1 -C $(BUILD_DIR)	
	cd $(BUILD_DIR); python setup.py build --build-lib build/lib
	touch $(MONOTONIC_DIR)/__init__.py
	cp -r $(BUILD_DIR)/build/lib/* $(MONOTONIC_DIR)
	rm -rf $(BUILD_DIR)

build: py_monotonic
	@echo

clean:
	rm -rf build dist $(MONOTONIC_DIR)

