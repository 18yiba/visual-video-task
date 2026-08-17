import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath =
  "D:\\QW_FILE\\visual-already_data\\output\\被试到访与费用记录.xlsx";

const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);

const overview = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 12000,
  tableMaxRows: 20,
  tableMaxCols: 20,
  tableMaxCellChars: 200,
});

console.log(overview.ndjson);
