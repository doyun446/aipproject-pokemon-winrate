$ErrorActionPreference = 'Stop'

$usageUrl = 'https://www.smogon.com/stats/2026-10'
$format = 'gen9championsbssregmc-1760'
$namesUrl = 'https://raw.githubusercontent.com/PokeAPI/pokeapi/4e84512eaf7f58a5a50d2a27941b1191cdb9e5e9/data/v2/csv'
$sourceDirectory = Join-Path $PSScriptRoot 'catalog-input'
$sources = @{
    "$format.json" = "$usageUrl/chaos/$format.json"
    "$format.txt" = "$usageUrl/$format.txt"
}
foreach ($name in 'pokemon_species_names.csv', 'move_names.csv', 'item_names.csv', 'ability_names.csv') {
    $sources[$name] = "$namesUrl/$name"
}

New-Item -ItemType Directory -Path $sourceDirectory -Force | Out-Null
foreach ($name in ($sources.Keys | Sort-Object)) {
    $destination = Join-Path $sourceDirectory $name
    $temporary = "$destination.tmp"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $sources[$name] -OutFile $temporary
        Move-Item -LiteralPath $temporary -Destination $destination -Force
        Write-Output $name
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary
        }
    }
}
