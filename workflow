name: clusterPodWorkflow
description: Run NRQL to get cluster names, then run NRQL again to get one pod per cluster

workflowInputs:
  accountId:
    type: Int

steps:
  - name: getClusters
    type: action
    action: newrelic.nrql.query
    version: 1
    inputs:
      accountId: ${{ .workflowInputs.accountId }}
      query: >
        FROM K8sPodSample
        SELECT latest(timestamp)
        FACET clusterName
        LIMIT MAX
        SINCE 30 minutes ago

  - name: loopClusters
    type: loop
    for:
      in: ${{ .steps.getClusters.outputs.results }}
    steps:
      - name: getPod
        type: action
        action: newrelic.nrql.query
        version: 1
        inputs:
          accountId: ${{ .workflowInputs.accountId }}
          query: >
            FROM K8sPodSample
            SELECT latest(podName)
            WHERE clusterName = '${{ .steps.loopClusters.loop.element.facet }}'
            LIMIT 1
            SINCE 30 minutes ago