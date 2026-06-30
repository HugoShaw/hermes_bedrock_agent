package com.hulft.adapter.sap;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.util.List;

/**
 * SAP RFC連携アダプタ
 * 発注データをSAP BAPIを経由して取得する
 */
public class SapOrderAdapter {

    private final SapConnectionConfig config;
    private final RetryPolicy retryPolicy;

    public SapOrderAdapter(SapConnectionConfig config) {
        this.config = config;
        this.retryPolicy = new RetryPolicy(3, 30000); // 3回, 30秒間隔
    }

    /**
     * BAPI_PO_GETDETAIL呼出し
     * @param poNumber 発注番号
     * @return 発注明細リスト
     */
    public List<OrderDetail> getOrderDetails(String poNumber) {
        JCoFunction function = repository.getFunction("BAPI_PO_GETDETAIL");
        function.getImportParameterList().setValue("PURCHASEORDER", poNumber);
        function.execute(destination);
        return mapResults(function.getTableParameterList().getTable("PO_ITEMS"));
    }

    /**
     * エラーハンドリング
     */
    private void handleError(Exception e) {
        logger.error("SAP RFC call failed: {}", e.getMessage());
        if (retryPolicy.shouldRetry()) {
            retryPolicy.wait();
            retry();
        }
    }
}
