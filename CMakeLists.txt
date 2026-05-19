# swarmit — opt-in CMake build for the device-side firmware
# (bootloader + netcore). SES (.emProject) projects continue to work
# unchanged. Python tooling is unaffected (and not driven by CMake).
#
# Quick start:
#
#   # Use bundled submodules (default — what CI does):
#   cmake -B build -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake -G Ninja
#   cmake --build build
#
#   # Cross-repo iteration: override paths to local checkouts.
#   cmake -B build -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake \
#         -DDOTBOT_LIBS=/path/to/DotBot-libs \
#         -DMARI=/path/to/mari \
#         -G Ninja
#
# Two targets:
#   - bootloader  (secure side, nRF5340 app core, hard float, emits
#                  cmse_implib.a for non-secure consumers)
#   - netcore     (nRF5340 net core, soft float, links mari + dotbot-libs
#                  netcore variants)

cmake_minimum_required(VERSION 3.20)

project(swarmit-device
    LANGUAGES C ASM
    VERSION 0.0.1
)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# CPU flags are PER-TARGET (bootloader: hard float; netcore: soft float),
# set inside each subdir's CMakeLists.txt. Common compile/link options
# below apply to both.

set(COMMON_FLAGS
    -ffunction-sections
    -fdata-sections
    -Wall
    -Wextra
    -Wno-missing-attributes
    -O0
    -g3
)

add_compile_options(${COMMON_FLAGS})
add_link_options(
    -Wl,--gc-sections
    -Wl,--print-memory-usage
    --specs=nosys.specs
    -nostartfiles
)

# ── dotbot-libs (owns Nordic + CMSIS FetchContent) ───────────────────
# dotbot-libs's CMakeLists owns the nrfx + CMSIS_5 FetchContent and
# exposes two INTERFACE targets:
#   * `dotbot_libs`   — BSP + drivers + pure-C startup (cpu.c)
#   * `dotbot_nordic` — only the Nordic + ARM headers
#
# The bootloader and netcore here ship their OWN System/startup.c, so
# they link `dotbot_nordic` (headers only) instead of `dotbot_libs`
# (which would double-define Reset_Handler / vector tables).
set(DOTBOT_LIBS "${CMAKE_CURRENT_SOURCE_DIR}/dotbot-libs"
    CACHE PATH "Path to dotbot-libs. Defaults to the bundled submodule.")

if(NOT EXISTS "${DOTBOT_LIBS}/CMakeLists.txt")
    message(FATAL_ERROR
        "DOTBOT_LIBS=${DOTBOT_LIBS} has no CMakeLists.txt. "
        "Either initialize the bundled submodule "
        "(git submodule update --init --recursive) or override "
        "-DDOTBOT_LIBS=/path/to/your/DotBot-libs checkout.")
endif()

add_subdirectory(${DOTBOT_LIBS} dotbot-libs-build EXCLUDE_FROM_ALL)

# ── mari ─────────────────────────────────────────────────────────────
set(MARI "${CMAKE_CURRENT_SOURCE_DIR}/mari"
    CACHE PATH "Path to mari. Defaults to the bundled submodule.")

if(NOT EXISTS "${MARI}/CMakeLists.txt")
    message(FATAL_ERROR
        "MARI=${MARI} has no CMakeLists.txt. "
        "Either initialize the bundled submodule "
        "(git submodule update --init --recursive) or override "
        "-DMARI=/path/to/your/mari checkout.")
endif()

add_subdirectory(${MARI} mari-build EXCLUDE_FROM_ALL)

# ── Device targets ───────────────────────────────────────────────────

add_subdirectory(device/bootloader)
add_subdirectory(device/network_core)
