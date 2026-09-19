cmake_minimum_required(VERSION 3.20)
project(tyche_freshness_prototype LANGUAGES CXX)
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
  message(FATAL_ERROR "This disposable prototype currently supports Linux only")
endif()
find_package(Threads REQUIRED)
set(PROTOTYPE_EVIDENCE_ROOT "${CMAKE_CURRENT_BINARY_DIR}" CACHE PATH "Parent directory for new evidence runs")
file(MAKE_DIRECTORY "${PROTOTYPE_EVIDENCE_ROOT}")
add_executable(freshness_probe main.cpp space.cpp)
target_compile_features(freshness_probe PRIVATE cxx_std_20)
target_compile_options(freshness_probe PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(freshness_probe PRIVATE Threads::Threads)
enable_testing()
add_test(NAME shared_memory_freshness_scenarios
  COMMAND ${CMAKE_COMMAND}
    -DPROBE=$<TARGET_FILE:freshness_probe>
    -DEVIDENCE_ROOT=${PROTOTYPE_EVIDENCE_ROOT}
    -P ${CMAKE_CURRENT_SOURCE_DIR}/run-scenarios.cmake)
set_tests_properties(shared_memory_freshness_scenarios PROPERTIES TIMEOUT 30)

add_executable(ordered_probe ordered_main.cpp space.cpp)
target_compile_features(ordered_probe PRIVATE cxx_std_20)
target_compile_options(ordered_probe PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(ordered_probe PRIVATE Threads::Threads)
add_test(NAME ordered_consumer_scenarios
  COMMAND ${CMAKE_COMMAND}
    -DPROBE=$<TARGET_FILE:ordered_probe>
    -DEVIDENCE_ROOT=${PROTOTYPE_EVIDENCE_ROOT}
    -P ${CMAKE_CURRENT_SOURCE_DIR}/run-scenarios.cmake)
set_tests_properties(ordered_consumer_scenarios PROPERTIES TIMEOUT 30)

find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_executable(independent_worker independent_worker.cpp space.cpp durable_consumer.cpp batch_publisher.cpp)
target_compile_features(independent_worker PRIVATE cxx_std_20)
target_compile_options(independent_worker PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(independent_worker PRIVATE Threads::Threads)
add_test(NAME independent_attachment_scenarios
  COMMAND ${CMAKE_COMMAND}
    -DPYTHON=${Python3_EXECUTABLE}
    -DWORKER=$<TARGET_FILE:independent_worker>
    -DSCENARIOS=${CMAKE_CURRENT_SOURCE_DIR}/independent_scenarios.py
    -DEVIDENCE_ROOT=${PROTOTYPE_EVIDENCE_ROOT}
    -P ${CMAKE_CURRENT_SOURCE_DIR}/run-independent.cmake)
set_tests_properties(independent_attachment_scenarios PROPERTIES TIMEOUT 80)

add_test(NAME crash_recovery_scenarios
  COMMAND ${CMAKE_COMMAND}
    -DPYTHON=${Python3_EXECUTABLE}
    -DWORKER=$<TARGET_FILE:independent_worker>
    -DSCENARIOS=${CMAKE_CURRENT_SOURCE_DIR}/crash_scenarios.py
    -DRUN_PREFIX=recovery
    -DRUN_TIMEOUT=170
    -DEVIDENCE_ROOT=${PROTOTYPE_EVIDENCE_ROOT}
    -P ${CMAKE_CURRENT_SOURCE_DIR}/run-independent.cmake)
set_tests_properties(crash_recovery_scenarios PROPERTIES TIMEOUT 180)

add_test(NAME bounded_batch_scenarios
  COMMAND ${CMAKE_COMMAND}
    -DPYTHON=${Python3_EXECUTABLE}
    -DWORKER=$<TARGET_FILE:independent_worker>
    -DSCENARIOS=${CMAKE_CURRENT_SOURCE_DIR}/batch_scenarios.py
    -DRUN_PREFIX=batch
    -DRUN_TIMEOUT=110
    -DEVIDENCE_ROOT=${PROTOTYPE_EVIDENCE_ROOT}
    -P ${CMAKE_CURRENT_SOURCE_DIR}/run-independent.cmake)
set_tests_properties(bounded_batch_scenarios PROPERTIES TIMEOUT 120)

# Short diagnostic only; deliberately not part of correctness CTest runs.
add_executable(capacity_probe capacity_probe.cpp space.cpp durable_consumer.cpp batch_publisher.cpp)
target_compile_features(capacity_probe PRIVATE cxx_std_20)
target_compile_options(capacity_probe PRIVATE -Wall -Wextra -Wpedantic -Werror)
target_link_libraries(capacity_probe PRIVATE Threads::Threads)
