from datetime import timedelta
from datetime import datetime as dt
import time
import logging
import logging.handlers
import google.cloud.logging
import sys
import arcpy


arcpy.env.workspace = "in_memory"  
arcpy.env.overwriteOutput = True
arcpy.env.preserveGlobalIds = True


def get_querylayer_for_yesterday(workspace, table_name, date_field, today=None):
    """Create a query layer that includes only data for the previous day."""
    if today is None:
        yesterday = dt.now() - timedelta(days=1)
    else:
        yesterday = today - timedelta(days=1)

    start_of_day = dt(yesterday.year, yesterday.month, yesterday.day)
    start_day_string = dt.strftime(start_of_day, "%Y-%m-%d %H:%M:%S")
    end_of_day = start_of_day + timedelta(days=1)
    end_day_string = dt.strftime(end_of_day, "%Y-%m-%d %H:%M:%S")
    log.info('Making query layer for {}. Date range: {} to {}'.format(
        table_name,
        start_day_string, 
        end_day_string))
    #where clause for the time range
    where_clause = \
    """
    select * from {table} 
    where 
    {field} >= '{start}'
    AND
    {field} < '{end}'
    """.format(
        table=table_name,
        field=date_field,
        start=start_day_string,
        end=end_day_string)
    
    ql_name = "date_query_result"
    ql_start_time = time.time()
    arcpy.MakeQueryLayer_management(
        workspace, ql_name, where_clause)
    log.info('Query Layer creation time: {} seconds'.format(round(time.time() - ql_start_time, 4)))
    
    return ql_name


def get_enriched_points(querylayer_points, enrichment_data, fields_to_keep):
    #defining features for the spatial join
    join_features = enrichment_data
    join_describe = arcpy.Describe(join_features)
    target_features = querylayer_points
    target_describe = arcpy.Describe(target_features)
    join_output = r"in_memory\spatial_join"
    temp_out_name = join_output
    n = 1
    while arcpy.Exists(temp_out_name):
        temp_out_name = join_output + str(n)
        n += 1
    join_output = temp_out_name


    log.info('Enriching {} with {}'.format(join_describe.name, target_describe.name))
    log.debug('Keep fields: {}'.format(','.join(fields_to_keep)))

    if join_describe.spatialReference.name != target_describe.spatialReference.name:
        log.warn('Spatial reference mismatch: join={}, target={}'.format(
            target_describe.spatialReference.name,
            join_describe.spatialReference.name))

    #field map to determine which fields to keep
    fieldmappings = arcpy.FieldMappings()
    # Add all fields from inputs.
    fieldmappings.addTable(join_features)
    fieldmappings.addTable(target_features)

    keep_fields = set([f.lower() for f in fields_to_keep])
    # Check that keep fields are actually in these data
    mapped_field_names = set([f.name.lower() for f in fieldmappings.fields])
    field_intersect = keep_fields.intersection(mapped_field_names)
    if field_intersect != keep_fields:
        log.warn('Keep fields not in either dataset: {}'.format(','.join(keep_fields - field_intersect)))

    for field in fieldmappings.fields:
        if field.name.lower() not in keep_fields:
            fieldmappings.removeFieldMap(
                fieldmappings.findFieldMapIndex(field.name))

    # Join datasets spatially
    join_start_time = time.time()
    arcpy.SpatialJoin_analysis(
        target_features, join_features,join_output,
        "JOIN_ONE_TO_ONE",
        "KEEP_ALL",
        fieldmappings)
    log.info('Join processing time: {} seconds'.format(round(time.time() - join_start_time, 4)))

    #removing uneeded fields created from join
    arcpy.DeleteField_management(join_output, ["Join_Count", "TARGET_FID"])

    return join_output


def mutliple_enrichment(querylayer_points, enrichment_features, fields_to_keep):
    """Enrich points with fields from list of feature classes."""
    
    # Check for fields that exist in multiple features. Join process will only use first field.
    field_names = []
    field_names.extend([f.name.lower() for f in arcpy.ListFields(querylayer_points)])
    for feature in enrichment_features:
        field_names.extend([f.name.lower() for f in arcpy.ListFields(feature)])
    for field in fields_to_keep:
        f_count = field_names.count(field.lower())
        if f_count > 1:
            log.warn('Field in multiple features: field={}, count={}'.format(field, f_count))
    
    enriched = querylayer_points
    for feature in enrichment_features:
        old_enriched = enriched
        enriched = get_enriched_points(
            enriched,
            feature,
            fields_to_keep)
        arcpy.Delete_management(old_enriched)
    
    return enriched



def full_landowner_enrich():
    start_date = "2002-02-01 12:00:00"
    stop_date = "2002-03-01 12:00:00"
    ending = "2004-06-01 12:00:00"


    start = dt.strptime(start_date, "%Y-%m-%d %H:%M:%S")
    stop = dt.strptime(stop_date, "%Y-%m-%d %H:%M:%S")
    end = dt.strptime(ending, "%Y-%m-%d %H:%M:%S")
    
    while start < end:
        print('Start', start, 'End', stop)

        #where clause for the time range
        where_clause = "select * from Collar.COLLARADMIN.Collars where DateYearAndJulian >=" + \
            "'{}'".format(start) + " AND " + \
            "DateYearAndJulian <=" + "'{}'".format(stop)

        #query layer created from the clause
        arcpy.MakeQueryLayer_management(
            r"enrichedPoints\collar.agrc.utah.gov.sde", "date_query_result", where_clause)

        #defining features for the spatial join
        join_features = r"H:\enrichedPoints.gdb\SGID10_Landownership"
        target_features = r"date_query_result"

        #field map to determine which fields to keep
        fieldmappings = arcpy.FieldMappings()
        # Add all fields from inputs.
        fieldmappings.addTable(join_features)
        fieldmappings.addTable(target_features)

        fields_sequence = ["OWNER",
                        "ADMIN", "COUNTY", "GlobalID"]
        for field in fieldmappings.fields:
            if field.name not in fields_sequence:
                fieldmappings.removeFieldMap(
                    fieldmappings.findFieldMapIndex(field.name))

        #joining the query layer with landownership and writing to in_memory
        arcpy.SpatialJoin_analysis(target_features, join_features, r"in_memory\spatial_join", "JOIN_ONE_TO_ONE", "KEEP_ALL", fieldmappings)

        #removing uneeded fields created from join
        arcpy.DeleteField_management( r"spatial_join", ["Join_Count", "TARGET_FID"])

        #appending the spatial join output to the master table of enriched points
        arcpy.Append_management(r"spatial_join", r"H:\enrichedPoints.gdb\enrichedPoints", "NO_TEST")


        arcpy.Delete_management(r"in_memory\spatial_join")

        #adding time to the start and stop date to pickup where it left off
        start = stop + timedelta(minutes=1)
        stop = stop + timedelta(days=30)

def _setup_logging():
    log_name = 'enricher'
    log = logging.getLogger(log_name)
    log.setLevel(logging.DEBUG)
    log_formatter = logging.Formatter(fmt='%(levelname)s: %(message)s')
    log.logThreads = 0
    log.logProcesses = 0

    client = google.cloud.logging.Client.from_service_account_json('../.keys/python-logging.json')
    sd_formatter = logging.Formatter(fmt='%(filename)s: %(message)s')
    sd_handler = client.get_default_handler()
    sd_handler.setFormatter(sd_formatter)
    sd_handler.setLevel(logging.ERROR)
    log.addHandler(sd_handler)

    file_handler = logging.handlers.RotatingFileHandler('enricher.log', backupCount=7)
    file_handler.doRollover()
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_formatter)
    
    log.addHandler(console_handler)
    log.addHandler(file_handler)

    return log_name

if __name__ == '__main__':
    workspace = r'C:\Users\kwalker\AppData\Roaming\ESRI\Desktop10.4\ArcCatalog\CollarTest as CollarAdmin.sde'
    collars_table = 'CollarTest.COLLARADMIN.Collars'
    date_field = 'DateYearAndJulian'

    log_name = _setup_logging()
    global log
    log = logging.getLogger(log_name)

    ql_name = get_querylayer_for_yesterday(
        workspace,
        collars_table,
        date_field,
        dt.strptime('2017-07-18', "%Y-%m-%d"))
    ql_count = arcpy.management.GetCount(ql_name)[0]
    log.info('Query layer point count: {}'.format(ql_count))

    enriched = mutliple_enrichment(
        ql_name,
        [r'C:\giswork\bqtest\DistrictCombinationAreas2012.gdb\DistrictCombinationAreas2012_wgs84',
         r'C:\giswork\vista\address_check2018\Counties.gdb\Counties'],
        ['Congress', 'Senate', 'House', 'CollarSerialNum', 'Latitude', 'POP_LASTCENSUS'])
    
    arcpy.management.CopyFeatures(enriched, r'C:\giswork\temp\geotab_sample.gdb\winnerwinner')
    arcpy.Delete_management(enriched)
    
    log.error('kaboom!!!')
    logging.shutdown()