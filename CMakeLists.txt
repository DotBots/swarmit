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

# ── Nordic MDK + ARM CMSIS-Core via FetchContent ─────────────────────
include(FetchContent)

FetchContent_Declare(nrfx
    GIT_REPOSITORY https://github.com/NordicSemiconductor/nrfx.git
    GIT_TAG        v3.5.0
    GIT_SHALLOW    TRUE
)
FetchContent_Declare(cmsis_core
    GIT_REPOSITORY https://github.com/ARM-software/CMSIS_5.git
    GIT_TAG        5.9.0
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(nrfx cmsis_core)

set(NRFX_MDK_INCLUDE   ${nrfx_SOURCE_DIR}/mdk                       CACHE INTERNAL "Nordic MDK headers")
set(CMSIS_CORE_INCLUDE ${cmsis_core_SOURCE_DIR}/CMSIS/Core/Include  CACHE INTERNAL "ARM CMSIS-Core headers")

# ── dotbot-libs ──────────────────────────────────────────────────────
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
