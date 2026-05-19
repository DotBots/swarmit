# bootloader — the swarmit secure-side bootloader. Runs on nRF5340 app
# core in TrustZone secure state, owns the SPU/SAU partitioning, and
# exposes 13 NSC entries (cmse_implib.c) that NS user apps call into.
#
# Build outputs:
#   bootloader.elf / .hex / .bin     ← flashable image
#   cmse_implib.a                    ← NSC import library, consumed by
#                                      dotbot-swarmit NS apps
#
# Known size constraint (gcc-arm-none-eabi vs armclang/SES):
#   The bootloader partition is 64 KiB (with 256 B reserved for the NSC
#   veneer region). The SES Release build fits because armclang produces
#   tighter .rodata for the lh2_decoder lookup tables. gcc-arm-none-eabi
#   even at -Os overflows by ~5 KiB. The final link emits cmse_implib.a
#   correctly (it happens before the FLASH-fit check, so NS apps still
#   get a valid import library), but the bootloader.elf does not fit.
#   Follow-up: either enable -flto, or prune unused decoder tables, or
#   move lh2 entirely to the net core. Out of scope for the CMake
#   migration — the build path is correct; the binary just exceeds the
#   partition budget under the GNU toolchain.

set(BL_LINKER_SCRIPT ${CMAKE_SOURCE_DIR}/cmake/targets/nrf5340-app-secure/nrf5340_bootloader.ld)

# Cortex-M33 + TrustZone secure (hard float).
set(BL_CPU_FLAGS
    -mcpu=cortex-m33
    -mthumb
    -mfloat-abi=hard
    -mfpu=fpv5-sp-d16
    -mcmse                        # enable __attribute__((cmse_nonsecure_entry))
)

add_executable(bootloader
    Source/main.c
    Source/battery.c
    Source/cmse_implib.c
    Source/ipc.c
    Source/localization.c
    Source/mari.c
    Source/nvmc.c
    Source/protocol.c
    Source/rng.c
    Source/tz.c
    System/startup.c
    System/system_init.c
    System/clock.c
    System/fault_handlers.c

    # dotbot-libs sources (listed individually — we DO NOT link the
    # dotbot_libs INTERFACE here because that target ships its own
    # pure-C startup at nRF/System/cpu.c, which would conflict with
    # the bootloader's System/startup.c).
    ${DOTBOT_LIBS}/bsp/nrf/board.c
    ${DOTBOT_LIBS}/bsp/nrf/gpio.c
    ${DOTBOT_LIBS}/bsp/nrf/timer.c
    ${DOTBOT_LIBS}/bsp/nrf/timer_hf.c
    ${DOTBOT_LIBS}/bsp/nrf/lh2.c
    ${DOTBOT_LIBS}/bsp/nrf/lh2_decoder.c
    ${DOTBOT_LIBS}/bsp/nrf/uart.c
    ${DOTBOT_LIBS}/bsp/nrf/saadc.c     # battery.c / cmse_implib.c call db_saadc_*
)

# Per-target CPU flags. Also override -O0 → -Os because the bootloader
# partition is only 64 KiB (less 256 B NSC region). With debug-build
# -O0 -g3 the .rodata section overflows; SES Release builds with -Os
# for the same reason.
target_compile_options(bootloader PRIVATE ${BL_CPU_FLAGS} -Os)

target_include_directories(bootloader PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/Source
    ${CMAKE_CURRENT_SOURCE_DIR}/System
    # Nordic MDK + ARM CMSIS-Core come via dotbot_nordic (linked below).
    ${DOTBOT_LIBS}/bsp
    ${DOTBOT_LIBS}/bsp/conf
    ${DOTBOT_LIBS}/drv
    ${DOTBOT_LIBS}/crypto   # sha256.h is at crypto/sha256.h, not crypto/sha256/
)

target_compile_definitions(bootloader PRIVATE
    NRF5340_XXAA
    NRF_APPLICATION
    __NRF_FAMILY
    ARM_MATH_ARMV8MML
    CONFIG_NFCT_PINS_AS_GPIOS
    BOARD_NRF5340DK
    USE_LH2
    USE_SWARMIT
    FLASH_PLACEMENT=1
)

target_link_libraries(bootloader PRIVATE
    dotbot_nordic   # headers-only INTERFACE: nrf.h + core_cm33.h
    m
)

target_link_options(bootloader PRIVATE
    ${BL_CPU_FLAGS}
    -T${BL_LINKER_SCRIPT}
    -Wl,-Map=${CMAKE_CURRENT_BINARY_DIR}/bootloader.map
    # Emit the NSC import library that NS apps will link against.
    -Wl,--cmse-implib
    -Wl,--out-implib=${CMAKE_CURRENT_BINARY_DIR}/cmse_implib.a
)

set_target_properties(bootloader PROPERTIES LINK_DEPENDS ${BL_LINKER_SCRIPT})

add_custom_command(TARGET bootloader POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O ihex   $<TARGET_FILE:bootloader> ${CMAKE_CURRENT_BINARY_DIR}/bootloader.hex
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:bootloader> ${CMAKE_CURRENT_BINARY_DIR}/bootloader.bin
    COMMAND ${CMAKE_SIZE} $<TARGET_FILE:bootloader>
    BYPRODUCTS ${CMAKE_CURRENT_BINARY_DIR}/bootloader.hex
               ${CMAKE_CURRENT_BINARY_DIR}/bootloader.bin
               ${CMAKE_CURRENT_BINARY_DIR}/cmse_implib.a
    COMMENT "bootloader: hex + bin (+ cmse_implib.a)"
)
