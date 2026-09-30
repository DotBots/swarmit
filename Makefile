DOCKER_IMAGE ?= aabadie/dotbot:latest
DOCKER_TARGETS ?= all
PACKAGES_DIR_OPT ?=
SEGGER_DIR ?= /opt/segger
BUILD_CONFIG ?= Release
# other possible build targets are "dotbot-v2" and "nrf5340dk"
BUILD_TARGET ?= dotbot-v3

.PHONY: bootloader netcore sample mari-gateway-schedules clean-bootloader clean-netcore clean-sample clean distclean docker

all: bootloader netcore sample

bootloader:
	@echo "\e[1mBuilding $@ application\e[0m"
	"$(SEGGER_DIR)/bin/emBuild" swarmit-bootloader-$(BUILD_TARGET).emProject -project $@ -config $(BUILD_CONFIG) $(PACKAGES_DIR_OPT) -rebuild -verbose
	@echo "\e[1mDone\e[0m\n"

netcore:
	@echo "\e[1mBuilding $@ application\e[0m"
	"$(SEGGER_DIR)/bin/emBuild" swarmit-netcore.emProject -project $@ -config $(BUILD_CONFIG) $(PACKAGES_DIR_OPT) -rebuild -verbose
	@echo "\e[1mDone\e[0m\n"

sample: bootloader
	@echo "\e[1mBuilding $@ application\e[0m"
	"$(SEGGER_DIR)/bin/emBuild" swarmit-sample-$(BUILD_TARGET).emProject -project $@ -config $(BUILD_CONFIG) $(PACKAGES_DIR_OPT) -rebuild -verbose
	@echo "\e[1mDone\e[0m\n"

# One Mari gateway net-core image per schedule, each a full rebuild, into
# mari/firmware/Output/schedules/03app_gateway_net-<schedule>.hex
mari-gateway-schedules:
	@echo "\e[1mBuilding $@\e[0m"
	SEGGER_DIR="$(SEGGER_DIR)" BUILD_CONFIG="$(BUILD_CONFIG)" PACKAGES_DIR_OPT="$(PACKAGES_DIR_OPT)" mari/firmware/build-schedules.sh
	@echo "\e[1mDone\e[0m\n"

clean-bootloader:
	"$(SEGGER_DIR)/bin/emBuild" swarmit-bootloader-$(BUILD_TARGET).emProject -config $(BUILD_CONFIG) -clean

clean-netcore:
	"$(SEGGER_DIR)/bin/emBuild" swarmit-netcore.emProject -config $(BUILD_CONFIG) -clean

clean-sample:
	"$(SEGGER_DIR)/bin/emBuild" swarmit-sample.emProject -config $(BUILD_CONFIG) -clean

clean: clean-bootloader clean-netcore clean-sample

distclean: clean

UID := $(shell id -u)
GID := $(shell id -g)

docker:
	docker run --rm -i \
		-u $(UID):$(GID) \
		-e BUILD_TARGET="$(BUILD_TARGET)" \
		-e BUILD_CONFIG="$(BUILD_CONFIG)" \
		-e PACKAGES_DIR_OPT="-packagesdir $(SEGGER_DIR)/packages" \
		-e PROJECTS="$(PROJECTS)" \
		-e SEGGER_DIR="$(SEGGER_DIR)" \
		-v $(PWD):/dotbot $(DOCKER_IMAGE) \
		make $(DOCKER_TARGETS)
