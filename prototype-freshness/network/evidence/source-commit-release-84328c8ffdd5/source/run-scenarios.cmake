# Each run keeps its own observations; reruns never overwrite earlier evidence.
string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef RUN_ID)
set(OUTPUT "${EVIDENCE_ROOT}/ctest-evidence-${RUN_ID}")
execute_process(COMMAND "${PROBE}" "${OUTPUT}"
  RESULT_VARIABLE RESULT TIMEOUT 25)
if(NOT RESULT EQUAL 0)
  message(FATAL_ERROR "Freshness scenarios failed: ${RESULT}; evidence: ${OUTPUT}")
endif()
