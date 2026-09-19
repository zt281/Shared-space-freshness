string(RANDOM LENGTH 12 ALPHABET 0123456789abcdef RUN_ID)
set(OUTPUT "${EVIDENCE_ROOT}/independent-evidence-${RUN_ID}")
execute_process(COMMAND "${PYTHON}" "${SCENARIOS}" "${WORKER}" "${OUTPUT}"
  RESULT_VARIABLE RESULT TIMEOUT 75)
if(NOT RESULT EQUAL 0)
  message(FATAL_ERROR "Independent attachment scenarios failed: ${RESULT}; evidence: ${OUTPUT}")
endif()
